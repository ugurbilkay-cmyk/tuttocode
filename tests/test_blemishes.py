"""Repair support, hotspot/keep-area preservation, authenticated masks and lifecycle."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image
from starlette.testclient import TestClient
from test_hotspots import fixture
from app import blemishes as B,config,db,main,processing as P,enhancement as E,enhancement_models as M,skin
from scripts.blemish_worker import repair_mask


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.rgb,self.points=fixture();self.rgb[183:192,103:112]=[100,75,55]
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        root=Path(self.folder.name);(root/'blemish').mkdir();(root/'blemish/joint_20210926.pth').touch()
        change=patch.object(config,'ENHANCER_MODEL_DIR',root);change.start();self.addCleanup(change.stop)

    def reply(self,args,**kwargs):
        self.assertNotIn('OPENAI_API_KEY',kwargs['env']);self.assertNotIn('ADMIN_PASSWORD',kwargs['env'])
        settings=E.validate(json.loads(args[args.index('--settings')+1]));source=Path(args[args.index('--input')+1]);target=Path(args[args.index('--output')+1])
        rgb=P.load_image(source.read_bytes());allowed=np.load(args[args.index('--allowed')+1],allow_pickle=False)
        mask=np.zeros(rgb.shape[:2],np.float32);mask[183:192,103:112]=allowed[183:192,103:112]*settings['blemish']/100
        out=rgb.copy();weight=mask[...,None]
        out=np.rint(rgb*(1-weight)+np.array([165,130,110])*weight).astype(np.uint8)
        out[5,5]=255  # Malformed off-mask change must be discarded by the bridge.
        Image.fromarray(out).save(target);np.save(target.with_suffix('.npy'),mask,allow_pickle=False)
        target.with_suffix('.json').write_text(json.dumps(dict(engine='blemish',model_sha256=M.MODELS['blemish']['files']['joint_20210926.pth'],
            code_revision=M.BLEMISH_CODE_REVISION,source_size=[rgb.shape[1],rgb.shape[0]],settings=settings,
            roi=json.loads(args[args.index('--roi')+1]),candidate_spots=1,inference_seconds=.1,
            mask_sha256=hashlib.sha256(mask.astype('<f4').tobytes()).hexdigest())))
        return subprocess.CompletedProcess(args,0,b'',b'')

    def test_default_is_exact_no_op_without_worker(self):
        with patch.object(B.subprocess,'run') as worker:
            out,record,assets=B.apply(self.rgb,self.points,{})
        worker.assert_not_called();np.testing.assert_array_equal(out,self.rgb);self.assertFalse(assets)

    def test_repair_changes_only_permitted_spot_and_preserves_highlight_metrics(self):
        source=self.rgb.copy()
        with patch.object(B.subprocess,'run',side_effect=self.reply) as worker:
            out,record,assets=B.apply(self.rgb,self.points,{'blemish':60})
            temporary=Path(worker.call_args.args[0][worker.call_args.args[0].index('--input')+1]).parent
        self.assertEqual(record['status'],'applied');self.assertGreater(record['edited_pixels'],0)
        np.testing.assert_array_equal(self.rgb,source);np.testing.assert_array_equal(out[5,5],source[5,5])
        self.assertEqual(record['before_hotspots']['regions'],record['after_hotspots']['regions'])
        self.assertTrue(record['preserved_hotspot_pixels']);self.assertFalse(temporary.exists())
        mask=np.array(Image.open(io.BytesIO(assets['mask'])))
        np.testing.assert_array_equal(out[mask==0],source[mask==0])
        self.assertEqual(set(assets),{'before','after','mask'})

    def test_keep_circle_excludes_spot_from_repair(self):
        with patch.object(B.subprocess,'run',side_effect=self.reply):
            out,record,assets=B.apply(self.rgb,self.points,{'blemish':100,'blemish_keep':[[107/320,187/320,.05]]})
        np.testing.assert_array_equal(out,self.rgb);self.assertEqual(record['edited_pixels'],0)
        self.assertEqual(record['status'],'unchanged')
        self.assertEqual(record['models'][0]['engine'],'blemish')
        self.assertEqual(record['kept_areas'],1)
        smoothed,_=skin.apply(out,self.points,100,[[107/320,187/320,.05]])
        protected=np.zeros(self.rgb.shape[:2],np.uint8);cv2.circle(protected,(107,187),16,1,-1)
        np.testing.assert_array_equal(smoothed[protected.astype(bool)],self.rgb[protected.astype(bool)])

    def test_source_protection_excludes_identifying_marks_before_worker_and_preserves_exact_pixels(self):
        protected=np.zeros(self.rgb.shape[:2],bool);protected[183:192,103:107]=True
        def reply(args,**kwargs):
            allowed=np.load(args[args.index('--allowed')+1],allow_pickle=False)
            self.assertFalse(allowed[protected].any())
            return self.reply(args,**kwargs)
        with patch.object(B.subprocess,'run',side_effect=reply):
            out,record,assets=B.apply(self.rgb,self.points,{'blemish':100},protected_mask=protected)
        np.testing.assert_array_equal(out[protected],self.rgb[protected])
        self.assertGreater(record['edited_pixels'],0)
        self.assertEqual(record['source_protected_pixels'],int(protected.sum()))
        self.assertTrue(record['source_protected_exact'])
        self.assertEqual(record['source_protected_mask_sha256'],hashlib.sha256(protected.tobytes()).hexdigest())
        actual_mask=np.array(Image.open(io.BytesIO(assets['mask'])))
        self.assertFalse(actual_mask[protected].any())

    def test_invalid_source_protection_cannot_launch_a_repair(self):
        for protected in (np.zeros((2,2),bool),np.full(self.rgb.shape[:2],np.nan),
                          np.full(self.rgb.shape[:2],2),np.full(self.rgb.shape[:2],'invalid')):
            with patch.object(B.subprocess,'run') as worker:
                out,record,assets=B.apply(self.rgb,self.points,{'blemish':50},protected_mask=protected)
            worker.assert_not_called();np.testing.assert_array_equal(out,self.rgb)
            self.assertEqual(record['status'],'unavailable');self.assertFalse(assets)

    def test_invalid_keep_regions_and_options_are_rejected(self):
        for values in ({'blemish':101},{'blemish_sensitivity':'auto'},{'blemish_size':'unknown'},
                       {'blemish_keep':'{bad'},{'blemish_keep':[[1,1,0]]},{'blemish_keep':[[float('nan'),0,.1]]},
                       {'blemish_keep':[[2,0,.1]]},{'blemish_keep':[[.5,.5,.01]]*257}):
            with self.assertRaises(ValueError):E.validate(values)

    def test_missing_model_or_bad_landmarks_are_advisory_and_keep_source(self):
        out,record,assets=B.apply(self.rgb,None,{'blemish':50})
        self.assertEqual(record['status'],'unavailable');np.testing.assert_array_equal(out,self.rgb)
        (config.ENHANCER_MODEL_DIR/'blemish/joint_20210926.pth').unlink()
        out,record,assets=B.apply(self.rgb,self.points,{'blemish':50})
        self.assertEqual(record['status'],'unavailable');np.testing.assert_array_equal(out,self.rgb)

    def test_timeout_and_invalid_mask_do_not_apply_a_partial_repair(self):
        with patch.object(B.subprocess,'run',side_effect=subprocess.TimeoutExpired('worker',300)):
            out,record,assets=B.apply(self.rgb,self.points,{'blemish':50})
        self.assertEqual(record['status'],'unavailable');np.testing.assert_array_equal(out,self.rgb)
        def corrupt(args,**kwargs):
            result=self.reply(args,**kwargs);target=Path(args[args.index('--output')+1])
            np.save(target.with_suffix('.npy'),np.full(self.rgb.shape[:2],np.nan,np.float32));return result
        with patch.object(B.subprocess,'run',side_effect=corrupt):out,record,assets=B.apply(self.rgb,self.points,{'blemish':60})
        self.assertEqual(record['status'],'unavailable');np.testing.assert_array_equal(out,self.rgb)

    def test_detection_threshold_and_spot_size_filter_are_separate_controls(self):
        probability=np.zeros((80,80),np.float32);probability[10:12,10:12]=.4;probability[20:22,20:22]=.8
        allowed=np.ones((80,80),np.float32)
        gentle,n,_=repair_mask(probability,allowed,'gentle','all');self.assertEqual(n,1)
        standard,n,_=repair_mask(probability,allowed,'standard','all');self.assertEqual(n,2)
        probability[40:60,40:60]=.8
        small,n,_=repair_mask(probability,allowed,'gentle','small');self.assertEqual(n,1)
        all_sizes,n,_=repair_mask(probability,allowed,'gentle','all');self.assertEqual(n,2)
        allowed[20:22,20:22]=0
        mask,_,_=repair_mask(probability,allowed,'gentle','all');self.assertFalse(mask[20:22,20:22].any())


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.rgb,self.points=fixture();buffer=io.BytesIO();Image.fromarray(self.rgb).save(buffer,'PNG');self.source=buffer.getvalue()
        class Analyzer:
            def analyze(inner,rgb):return P.Analysis([P.FaceData(self.points,{})],np.ones(rgb.shape[:2],np.float32))
        P._analyzer=Analyzer();db.init()
        self.client=TestClient(main.app,headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-only').decode()})
        self.artifacts={name:B.png(self.rgb if name!='mask' else np.ones(self.rgb.shape[:2],np.uint8)*100) for name in ['before','after','mask']}

    def repaired(self,rgb,points,values):
        return rgb,dict(phase='blemish',status='applied',models=[],candidate_spots=1,edited_pixels=1,message='Test repair'),self.artifacts

    def upload(self):
        with patch.object(B,'apply',side_effect=self.repaired):
            response=self.client.post('/admin/new',data={'opts':'1','print_only':'on','enhancer_blemish':'50'},files={'photo':('x.png',self.source)},follow_redirects=False)
        self.assertEqual(response.status_code,303,response.text);return response.headers['location'].rsplit('/',1)[1]

    def test_authenticated_mask_and_previews_and_review_dialog(self):
        pid=self.upload();revision=db.get(pid)['revision']
        for name in ['before','after','mask']:
            path=f'/admin/p/{pid}/cleaner/{name}.png?revision={revision}'
            self.assertEqual(self.client.get(path).status_code,200)
            self.assertEqual(self.client.get(path,headers={'Authorization':''}).status_code,401)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/cleaner/mask.png?revision=-1').status_code,409)
        page=self.client.get(f'/admin/p/{pid}').text
        self.assertIn('Review skin repairs',page);self.assertIn('blemish-keep',page)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/cleaner/unknown.png').status_code,404)

    def test_disabling_cleaner_clears_old_masks_and_restore_is_source_based(self):
        pid=self.upload()
        response=self.client.post(f'/admin/p/{pid}/reprocess',data={'opts':'1','print_only':'on'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/cleaner/mask.png').status_code,404)
        self.assertTrue((config.PHOTO_DIR/(pid+'_source')).exists())

    def test_keep_areas_survive_reprocess_but_clear_when_framing_changes(self):
        pid=self.upload();v='[[0.5,0.5,0.01]]'
        form={'opts':'1','print_only':'on','enhancer_blemish':'50','enhancer_blemish_keep':v,'cleaner_revision':str(db.get(pid)['revision'])}
        with patch.object(B,'apply',side_effect=self.repaired) as model:
            self.assertEqual(self.client.post(f'/admin/p/{pid}/reprocess',data=form,follow_redirects=False).status_code,303)
            self.assertEqual(model.call_args.args[2]['blemish_keep'],[[.5,.5,.01]])
            form['cleaner_revision']=str(db.get(pid)['revision']);form['x']='1'
            self.assertEqual(self.client.post(f'/admin/p/{pid}/reprocess',data=form,follow_redirects=False).status_code,303)
            self.assertEqual(model.call_args.args[2]['blemish_keep'],[])
        form['cleaner_revision']='-1'
        self.assertEqual(self.client.post(f'/admin/p/{pid}/reprocess',data=form,follow_redirects=False).status_code,409)

    def test_expiry_removes_cleaner_artifacts(self):
        pid=self.upload()
        with db.conn() as c:c.execute('UPDATE photos SET expires=? WHERE id=?',(time.time()-1,pid))
        self.assertEqual(self.client.get(f'/admin/p/{pid}/cleaner/mask.png').status_code,404)
        db.purge_expired()
        for name in ['before','after','mask']:self.assertFalse((config.PHOTO_DIR/(pid+'_clean_'+name+'.png')).exists())

    def test_issued_photo_retains_read_only_repair_review(self):
        pid=self.upload()
        with db.conn() as c:c.execute("UPDATE photos SET status='issued',code='test-code' WHERE id=?",(pid,))
        page=self.client.get(f'/admin/p/{pid}').text
        self.assertIn('id="open-cleaner"',page);self.assertNotIn('id="cleaner-use"',page)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/cleaner/mask.png').status_code,200)


if __name__=='__main__':unittest.main()
