"""Matting transport, source geometry, soft-edge fidelity and staff workflow.

Heavy inference is mocked here; real installed models are checked separately.
"""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="tuttocode-bg-tests-"),ADMIN_PASSWORD="test-only",
                  OPENAI_API_KEY="",HMPO_KEY_URL="",BACKGROUND_MODEL_DIR=tempfile.mkdtemp(prefix="tuttocode-bg-models-"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from starlette.testclient import TestClient
from app import background as B, background_models as M, config, processing as P, db, main, ai_prepare
from synthetic import make_face,Fake


def photo():
    stream=io.BytesIO();Image.new("RGB",(80,100),(70,95,130)).save(stream,"PNG")
    return stream.getvalue()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.models=Path(self.folder.name)
        for engine,spec in M.MODELS.items():
            root=self.models/engine;root.mkdir()
            for filename in spec["files"]:(root/filename).write_bytes(b"test fixture, not real weights")
        self.patch=patch.object(config,"BACKGROUND_MODEL_DIR",self.models);self.patch.start();self.addCleanup(self.patch.stop)
        B._cache=None
        self.rgb=np.full((100,80,3),100,np.uint8)

    def reply(self,args,**kwargs):
        engine=args[args.index("--engine")+1];output=Path(args[args.index("--output")+1])
        with Image.open(args[args.index("--input")+1]) as image:
            size=list(image.size)
        alpha=np.full((size[1],size[0]),.5,np.float32)
        np.save(output,alpha)
        weight="model.onnx" if engine=="modnet" else "model.safetensors"
        output.with_suffix('.json').write_text(json.dumps(dict(engine=engine,model_sha256=M.MODELS[engine]['files'][weight],
                                                              source_size=size,inference_seconds=.1)))
        return subprocess.CompletedProcess(args,0,b"",b"")

    def test_opaque_pixels_exact_and_soft_hair_not_blurred(self):
        rgb=np.array([[[22,50,80],[100,80,60],[90,120,70]]],np.uint8)
        alpha=np.array([[1,.5,0]],np.float32)
        out=B.composite(rgb,alpha,(228,228,228))
        np.testing.assert_array_equal(out[0,0],rgb[0,0])
        np.testing.assert_array_equal(out[0,1],[164,154,144])
        np.testing.assert_array_equal(out[0,2],[228,228,228])
        np.testing.assert_array_equal(rgb[0,0],[22,50,80])

    def test_worker_environment_has_no_api_or_shop_secrets(self):
        with patch.dict(os.environ,OPENAI_API_KEY="secret",ADMIN_PASSWORD="secret",SMTP_PASSWORD="secret",HF_TOKEN="secret"):
            env=B._worker_environment()
        self.assertFalse(any(name in env for name in ['OPENAI_API_KEY','ADMIN_PASSWORD','SMTP_PASSWORD','HF_TOKEN']))
        self.assertEqual(env['HF_HUB_OFFLINE'],'1');self.assertEqual(env['TRANSFORMERS_OFFLINE'],'1')

    def test_source_cache_reuses_mask_and_return_is_not_mutable_cache(self):
        with patch.object(B.subprocess,'run',side_effect=self.reply) as worker:
            alpha,first=B.matte(self.rgb,'hr');alpha[:]=0
            second,evidence=B.matte(self.rgb.copy(),'hr')
            self.assertEqual(worker.call_count,1);self.assertEqual(second.mean(),.5)
            self.assertFalse(first['cache_hit']);self.assertTrue(evidence['cache_hit'])
            self.assertEqual(len(evidence['source_rgb_sha256']),64);self.assertEqual(len(evidence['alpha_sha256']),64)
            temporary=Path(worker.call_args.args[0][-1]).parent
        self.assertFalse(temporary.exists())

    def test_changed_source_model_or_bundle_invalidates_cache(self):
        with patch.object(B.subprocess,'run',side_effect=self.reply) as worker:
            B.matte(self.rgb,'hr');B.matte(self.rgb,'portrait')
            changed=self.rgb.copy();changed[0,0,0]+=1;B.matte(changed,'portrait')
            (self.models/'portrait/config.json').write_bytes(b'changed asset');B.matte(changed,'portrait')
            self.assertEqual(worker.call_count,4)

    def test_expiry_purge_clears_memory_mask(self):
        db.init()
        with patch.object(B.subprocess,'run',side_effect=self.reply):B.matte(self.rgb,'hr')
        self.assertIsNotNone(B._cache)
        db.create('expired-bg-cache','shop','adult',P.Result(False,[]))
        with db.conn() as connection:
            connection.execute("UPDATE photos SET expires=0 WHERE id=?",('expired-bg-cache',))
        db.purge_expired();self.assertIsNone(B._cache)

    def test_uninstalled_engine_never_substitutes_baseline(self):
        (self.models/'hr/model.safetensors').unlink()
        with patch.object(B.subprocess,'run') as worker:
            with self.assertRaises(B.Unavailable):B.matte(self.rgb,'hr')
            worker.assert_not_called()

    def test_bad_worker_alpha_and_provenance_are_rejected(self):
        for failure in ['shape','nan','empty','provenance']:
            def corrupt(args,**kwargs):
                self.reply(args,**kwargs);out=Path(args[-1])
                if failure=='provenance':out.with_suffix('.json').write_text(json.dumps(dict(engine='hr',model_sha256='wrong')))
                else:np.save(out, np.zeros((2,2)) if failure=='shape' else np.full((100,80),np.nan if failure=='nan' else 0))
                return subprocess.CompletedProcess(args,0,b'',b'')
            with patch.object(B.subprocess,'run',side_effect=corrupt):
                with self.assertRaises(B.Unavailable):B.matte(self.rgb,'hr')

    def test_timeout_and_worker_error_do_not_leak_payloads(self):
        for outcome in [subprocess.TimeoutExpired(['worker','secret'],.1),subprocess.CompletedProcess([],1,b'',b'secret-private-traceback')]:
            with patch.object(B.subprocess,'run',side_effect=outcome if isinstance(outcome,Exception) else None,return_value=outcome):
                with self.assertRaises(B.Unavailable) as caught:B.matte(self.rgb,'hr')
                self.assertNotIn('secret',str(caught.exception))

    def test_cross_thread_slot_serializes_heavy_inference(self):
        entered=threading.Event();finished=[]
        def other():
            entered.set()
            with B._worker_slot():finished.append(True)
        with B._worker_slot():
            thread=threading.Thread(target=other);thread.start();entered.wait(1)
            time.sleep(.15);self.assertFalse(finished)
        thread.join(2);self.assertEqual(finished,[True])

    def test_corrupt_snapshot_stops_before_loading_custom_code(self):
        out=self.models/'alpha.npy'
        reply=subprocess.run([sys.executable,str(config.BASE_DIR/'scripts/background_worker.py'),'--engine','hr',
                              '--models',str(self.models),'--input',str(self.models/'unused.png'),'--output',str(out)],capture_output=True)
        self.assertNotEqual(reply.returncode,0);self.assertIn(b'differs from pinned',reply.stderr);self.assertFalse(out.exists())


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        P._analyzer=Fake(P.Analysis([],None));db.init()
        self.client=TestClient(main.app,headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-only').decode()})

    def test_staff_tool_choice_is_persisted_and_never_calls_openai(self):
        alpha=np.full((100,80),.5,np.float32)
        evidence=dict(engine='portrait',label=M.LABELS['portrait'],status='applied',inference_seconds=.1)
        with patch.object(B,'matte',return_value=(alpha,evidence)),patch.object(ai_prepare,'prepare') as remote:
            response=self.client.post('/admin/new',data=dict(opts='1',print_only='on',replace_bg='on',background_engine='portrait'),
                                      files={'photo':('photo.png',photo())},follow_redirects=False)
            self.assertEqual(response.status_code,303,response.text);pid=response.headers['location'].split('/')[-1]
            row=db.get(pid);self.assertEqual(json.loads(row['options'])['background_engine'],'portrait')
            self.assertEqual(json.loads(row['measurements'])['background_removal']['engine'],'portrait')
            page=self.client.get('/admin/p/'+pid).text;self.assertIn('Background: Faster detail',page)
            self.assertIn('value="portrait" selected',page);remote.assert_not_called()
        self.assertFalse(row['ok']);self.assertTrue(main._photo_path(pid).exists())

    def test_unavailable_matting_keeps_output_and_visible_warning(self):
        flags=dict(print_only=True,auto_adjust=False,fix_shadows=False,even_bg=False)
        baseline=P.process(photo(),**flags,replace_bg=False)
        with patch.object(B,'matte',side_effect=B.Unavailable('Missing model')):
            result=P.process(photo(),**flags,replace_bg=True,background_engine='hr')
        self.assertEqual(result.jpeg,baseline.jpeg)
        self.assertEqual(result.measurements['background_removal']['status'],'unavailable')
        self.assertTrue(any(c.key=='background_tool' and c.status=='warn' for c in result.checks))

    def test_no_background_selection_never_launches_worker(self):
        with patch.object(B,'matte') as worker:
            P.process(photo(),print_only=True,replace_bg=False,auto_adjust=False)
            worker.assert_not_called()

    def test_unknown_engine_rejected_and_default_is_high_detail(self):
        self.assertEqual(main._opts()['background_engine'],'hr')
        response=self.client.post('/admin/new',data={'opts':'1','background_engine':'arbitrary-command'},files={'photo':('p.png',photo())})
        self.assertEqual(response.status_code,400)

    def test_native_source_mask_keeps_existing_crop_geometry(self):
        source,analysis=make_face();P._analyzer=Fake(analysis)
        options=dict(auto_adjust=False,fix_shadows=False,even_bg=False)
        original=P.process(source,replace_bg=False,**options)
        with patch.object(B,'matte',return_value=(analysis.person_mask,dict(label=M.LABELS['hr'],engine='hr',status='applied'))) as worker:
            result=P.process(source,replace_bg=True,background_engine='hr',**options)
        self.assertEqual(worker.call_args.args[0].shape,analysis.person_mask.shape+(3,))
        for key in ['source_crop_size','eye1','eye2','head_percent','output_size']:
            self.assertEqual(result.measurements[key],original.measurements[key])
        self.assertTrue(result.jpeg)


if __name__=='__main__':unittest.main()
