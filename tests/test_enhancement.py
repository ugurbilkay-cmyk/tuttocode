"""Enhancer isolation, native geometry, tiling and staff workflow regression checks."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='tuttocode-enhancer-tests-'),ADMIN_PASSWORD='test-only',
                  OPENAI_API_KEY='',HMPO_KEY_URL='')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from PIL import Image
from starlette.testclient import TestClient
from app import enhancement as E,enhancement_models as M,config,processing as P,main,db,ai_prepare
from scripts.enhancement_worker import tiled,verify
from synthetic import make_face,Fake


class EnhancerTests(unittest.TestCase):
    def setUp(self):
        self.rgb=np.random.default_rng(9).integers(20,220,(75,83,3),dtype=np.uint8)

    def test_default_is_exact_no_op_and_no_worker_or_remote_call(self):
        with patch.object(E.subprocess,'run') as worker,patch.object(ai_prepare,'prepare') as remote:
            for phase in ['restore','upscale']:
                out,record=E.apply(self.rgb,phase=phase)
                np.testing.assert_array_equal(out,self.rgb);self.assertEqual(record['status'],'unchanged')
            worker.assert_not_called();remote.assert_not_called()
        self.assertFalse(E.active())

    def test_invalid_settings_and_unsupported_factors_are_rejected(self):
        for value in [{'scale':3},{'scale':2.1},{'denoise':-1},{'lighting':101},{'detail':'nan'},
                      {'upscale_strength':float('inf')},{'upscale_engine':'unknown'},{'unknown':1},[]]:
            with self.assertRaises(ValueError):E.validate(value)

    def test_detail_is_local_same_shape_and_does_not_mutate_source(self):
        original=self.rgb.copy()
        with patch.object(E.subprocess,'run') as worker:
            out,record=E.apply(self.rgb,{'detail':35})
            worker.assert_not_called()
        self.assertEqual(out.shape,self.rgb.shape);self.assertEqual(out.dtype,np.uint8)
        np.testing.assert_array_equal(self.rgb,original)
        self.assertEqual(record['status'],'applied');self.assertNotEqual(record['source_rgb_sha256'],record['output_rgb_sha256'])
        flat=np.full((40,40,3),90,np.uint8)
        np.testing.assert_array_equal(E.apply(flat,{'detail':100})[0],flat)

    def test_upscale_zero_strength_uses_interpolation_without_a_model(self):
        with patch.object(E.subprocess,'run') as worker:
            out,record=E.apply(self.rgb,{'scale':2,'upscale_strength':0},phase='upscale')
            worker.assert_not_called()
        self.assertEqual(out.shape,(150,166,3));self.assertEqual(record['models'],[])
        with patch.object(E.subprocess,'run') as worker:
            out,record=E.apply(self.rgb,{'scale':4,'upscale_engine':'lanczos'},phase='upscale')
            self.assertEqual(out.shape,(300,332,3));worker.assert_not_called()

    def test_fixed_tiles_match_identity_and_nearest_scale_across_boundaries(self):
        # Non-square, multiple tiles, remainder strips and one-pixel edges.
        for h,w in [(75,83),(1,5),(5,1)]:
            rgb=self.rgb[:h,:w]
            prediction=tiled(rgb,lambda x:x,tile=32,scale=1,halo=4)
            np.testing.assert_allclose(prediction,rgb/255,atol=1e-7)
            prediction=tiled(rgb,lambda x:np.repeat(np.repeat(x,2,axis=2),2,axis=3),tile=32,scale=2,halo=4)
            np.testing.assert_allclose(prediction,np.repeat(np.repeat(rgb/255,2,axis=0),2,axis=1),atol=1e-7)
        with self.assertRaises(ValueError):tiled(self.rgb,lambda x:np.full_like(x,np.nan),32,1,4)

    def test_missing_model_preserves_stage_and_reports_unavailable(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'ENHANCER_MODEL_DIR',Path(folder)):
            out,record=E.apply(self.rgb,{'denoise':40})
        np.testing.assert_array_equal(out,self.rgb);self.assertEqual(record['status'],'unavailable')

    def test_changed_model_fails_digest_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'model';p.write_bytes(b'changed')
            with self.assertRaises(ValueError):verify(p,'0'*64)

    def test_worker_provenance_timeout_isolation_and_temp_cleanup(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'ENHANCER_MODEL_DIR',Path(folder)):
            root=Path(folder)/'nafnet';root.mkdir();(root/'model.onnx').touch()
            def reply(args,**kwargs):
                self.assertNotIn('OPENAI_API_KEY',kwargs['env']);self.assertNotIn('ADMIN_PASSWORD',kwargs['env'])
                source=Path(args[args.index('--input')+1]);target=Path(args[args.index('--output')+1])
                target.write_bytes(source.read_bytes())
                target.with_suffix('.json').write_text(json.dumps(dict(phase='restore',settings=E.validate({'denoise':25}),
                    source_size=[83,75],models=[dict(engine='nafnet',model_sha256=M.MODELS['nafnet']['files']['model.onnx'])])))
                return subprocess.CompletedProcess(args,0,b'',b'')
            with patch.object(E.subprocess,'run',side_effect=reply) as worker:
                out,record=E.apply(self.rgb,{'denoise':25})
                self.assertEqual(record['status'],'applied');np.testing.assert_array_equal(out,self.rgb)
                temporary=Path(worker.call_args.args[0][worker.call_args.args[0].index('--input')+1]).parent
            self.assertFalse(temporary.exists())
            with patch.object(E.subprocess,'run',side_effect=subprocess.TimeoutExpired('worker',300)):
                out,record=E.apply(self.rgb,{'denoise':25})
                self.assertEqual(record['status'],'unavailable');np.testing.assert_array_equal(out,self.rgb)

    def test_wrong_model_provenance_cannot_be_recorded_as_applied(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'ENHANCER_MODEL_DIR',Path(folder)):
            root=Path(folder)/'nafnet';root.mkdir();(root/'model.onnx').touch()
            def reply(args,**kwargs):
                source=Path(args[args.index('--input')+1]);target=Path(args[args.index('--output')+1])
                target.write_bytes(source.read_bytes())
                target.with_suffix('.json').write_text(json.dumps(dict(phase='restore',settings=E.validate({'denoise':25}),
                    source_size=[83,75],models=[dict(engine='nafnet',model_sha256='0'*64)])))
                return subprocess.CompletedProcess(args,0,b'',b'')
            with patch.object(E.subprocess,'run',side_effect=reply):out,record=E.apply(self.rgb,{'denoise':25})
            self.assertEqual(record['status'],'unavailable');np.testing.assert_array_equal(out,self.rgb)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source,self.analysis=make_face();P._analyzer=Fake(self.analysis)
        self.client=TestClient(main.app,headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-only').decode()})
        db.init()

    def upload(self,data=None,**fields):
        response=self.client.post('/admin/new',data={'opts':'1',**fields},files={'photo':('camera.jpg',data or self.source)},follow_redirects=False)
        self.assertEqual(response.status_code,303,response.text)
        return response.headers['location'].rsplit('/',1)[1]

    def test_ui_has_adaptive_profiles_without_model_controls(self):
        page=self.client.get('/admin').text
        self.assertIn('enhancer-presets',page);self.assertIn('Recovery',page)
        self.assertIn('adaptive_profile',page);self.assertNotIn('enhancer_upscale_strength',page)
        self.assertNotIn('NAFNet',page);self.assertNotIn('Retinexformer',page)
        self.assertEqual(self.client.post('/admin/new',data={'opts':'1','enhancer_scale':'3'},files={'photo':('x.jpg',self.source)}).status_code,400)

    def test_detail_edits_are_repeatable_from_source_and_restore_clears_them(self):
        with patch.object(ai_prepare,'prepare') as remote:
            pid=self.upload(enhancer_detail='25');first=main._photo_path(pid).read_bytes()
            response=self.client.post(f'/admin/p/{pid}/reprocess',data={'opts':'1','enhancer_detail':'25'},follow_redirects=False)
            self.assertEqual(response.status_code,303);self.assertEqual(main._photo_path(pid).read_bytes(),first)
            remote.assert_not_called()
        self.assertEqual(json.loads(db.get(pid)['options'])['enhancement_options']['detail'],25)
        self.assertEqual(self.client.post(f'/admin/p/{pid}/restore-original',follow_redirects=False).status_code,303)
        self.assertNotIn('local_enhancement',json.loads(db.get(pid)['measurements']))

    def test_enlargement_scales_output_landmarks_but_not_source_evidence(self):
        before=P.process(self.source,auto_adjust=False,fix_shadows=False,even_bg=False,replace_bg=False)
        enlarged=P.process(self.source,auto_adjust=False,fix_shadows=False,even_bg=False,replace_bg=False,
                           enhancement_options={'scale':2,'upscale_strength':0})
        with Image.open(io.BytesIO(enlarged.jpeg)) as image:
            self.assertEqual(image.size,tuple(v*2 for v in before.measurements['output_size']))
        self.assertEqual(enlarged.measurements['input_size'],before.measurements['input_size'])
        self.assertEqual(enlarged.measurements['source_eye_distance'],before.measurements['source_eye_distance'])
        self.assertAlmostEqual(enlarged.measurements['eye1'][0],before.measurements['eye1'][0]*2,places=1)
        self.assertEqual(enlarged.measurements['head_percent'],before.measurements['head_percent'])
        self.assertTrue(all(v<=s+1 for v,s in zip(enlarged.measurements['quality_sampling_size'],before.measurements['source_crop_size'])))

    def test_small_full_frame_still_prints_with_resolution_failure_after_upscale(self):
        buffer=io.BytesIO();Image.new('RGB',(80,100),(80,90,100)).save(buffer,'PNG')
        pid=self.upload(buffer.getvalue(),print_only='on',enhancer_scale='2',enhancer_upscale_strength='0')
        row=db.get(pid);self.assertFalse(row['ok']);self.assertIsNone(row['code'])
        self.assertTrue(any(c['key']=='resolution' and c['status']=='fail' for c in json.loads(row['checks'])))
        self.assertEqual(json.loads(row['measurements'])['input_size'],[80,100])
        for path in ['save.jpg','sheet.jpg','original.jpg']:
            self.assertEqual(self.client.get(f'/admin/p/{pid}/'+path).status_code,200)

    def test_issued_enhanced_job_keeps_original_and_review_settings(self):
        pid=self.upload(enhancer_detail='20')
        passing=P.Result(True,[P.Check('quality','Exact JPEG','pass')])
        with patch.object(P,'check_code_photo',return_value=passing):
            response=self.client.post(f'/admin/p/{pid}/issue',data={'review_likeness':'on','review_visibility':'on',
                'customer_permission':'on','review_revision':str(db.get(pid)['revision'])},follow_redirects=False)
        self.assertEqual(response.status_code,303,response.text)
        self.assertTrue((config.PHOTO_DIR/(pid+'_source')).exists())
        review=json.loads(db.get(pid)['issue_review'])
        self.assertEqual(review['processing_options']['enhancement_options']['detail'],20)
        self.assertEqual(len(review['photo_sha256']),64)


if __name__=='__main__':unittest.main()
