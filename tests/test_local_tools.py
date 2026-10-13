"""Local tone operations, free-first workflow and accountable staff overrides."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="tuttocode-local-tests-"),
                  ADMIN_PASSWORD="test-only", OPENAI_API_KEY="", HMPO_KEY_URL="")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from starlette.testclient import TestClient
from app import config, db, main, processing as P, local_adjustments as L, ai_prepare
from synthetic import Fake, make_face


class ToneTests(unittest.TestCase):
    def test_neutral_settings_are_an_exact_no_op(self):
        rgb=np.random.default_rng(10).integers(0,256,(70,90,3),dtype=np.uint8)
        out,notes=L.apply(rgb)
        np.testing.assert_array_equal(out,rgb)
        self.assertEqual(notes,[])

    def test_exposure_brightness_and_white_balance_have_expected_direction(self):
        rgb=np.full((40,40,3),80,np.uint8)
        self.assertGreater(L.apply(rgb,{'exposure':.5})[0].mean(),rgb.mean())
        self.assertLess(L.apply(rgb,{'exposure':-.5})[0].mean(),rgb.mean())
        self.assertGreater(L.apply(rgb,{'brightness':10})[0].mean(),rgb.mean())
        warm=L.apply(rgb,{'temperature':20})[0]
        self.assertGreater(warm[...,0].mean(),warm[...,2].mean())
        magenta=L.apply(rgb,{'tint':20})[0]
        self.assertGreater(magenta[...,0].mean(),magenta[...,1].mean())

    def test_highlight_compression_is_monotone_and_does_not_recover_flat_detail(self):
        rgb=np.repeat(np.arange(256,dtype=np.uint8)[None,:,None],3,axis=2)
        out,_=L.apply(rgb,{'highlights':100})
        self.assertTrue((np.diff(out[0,:,0].astype(int))>=0).all())
        self.assertLess(out[0,-1,0],255)
        flat=np.full((20,20,3),255,np.uint8)
        self.assertEqual(L.apply(flat,{'highlights':100})[0].std(),0)

    def test_shadow_lift_is_stronger_in_dark_tones(self):
        dark=np.full((20,20,3),50,np.uint8);light=np.full((20,20,3),220,np.uint8)
        self.assertGreater(L.apply(dark,{'shadows':100})[0].mean()-50,
                           L.apply(light,{'shadows':100})[0].mean()-220)

    def test_controls_keep_raster_geometry_and_source_unchanged(self):
        rgb=np.random.default_rng(2).integers(20,235,(65,80,3),dtype=np.uint8);original=rgb.copy()
        values={c['key']:c['maximum'] for c in L.CONTROLS}
        out,notes=L.apply(rgb,values)
        self.assertEqual(out.shape,rgb.shape);self.assertEqual(out.dtype,np.uint8)
        np.testing.assert_array_equal(rgb,original)
        np.testing.assert_array_equal(out,L.apply(rgb,values)[0])
        self.assertEqual(len(notes),len(L.CONTROLS))

    def test_invalid_values_are_rejected_before_processing(self):
        for values in ({'exposure':float('nan')},{'contrast':float('inf')},{'brightness':21},{'shadows':-1},{'unknown':2}):
            with self.assertRaises(ValueError):L.validate(values)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source,self.analysis=make_face();P._analyzer=Fake(self.analysis)
        self.client=TestClient(main.app,headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-only').decode()})
        db.init()

    def upload(self,data=None,**fields):
        r=self.client.post('/admin/new',data={'opts':'1',**fields},files={'photo':('camera.jpg',data or self.source)},follow_redirects=False)
        self.assertEqual(r.status_code,303,r.text)
        return r.headers['location'].rsplit('/',1)[1]

    def issue(self,pid,**fields):
        return self.client.post(f'/admin/p/{pid}/issue',data={'review_likeness':'on','review_visibility':'on','customer_permission':'on','review_revision':str(db.get(pid)['revision']),**fields},follow_redirects=False)

    def test_local_upload_never_calls_openai_and_is_not_selected_by_default(self):
        with patch.object(config,'OPENAI_API_KEY','test-secret'),patch.object(ai_prepare,'prepare') as remote:
            page=self.client.get('/admin').text
            tag=page.split('id="use-ai"',1)[1].split('>',1)[0]
            self.assertNotIn('checked',tag)
            self.assertIn('Optional OpenAI upgrade',page)
            pid=self.upload(exposure='.3',highlights='20')
            remote.assert_not_called()
        self.assertEqual(json.loads(db.get(pid)['options'])['adjustments']['exposure'],.3)

    def test_reprocessing_starts_from_source_not_previous_export(self):
        pid=self.upload(exposure='.5')
        first=main._photo_path(pid).read_bytes()
        r=self.client.post(f'/admin/p/{pid}/reprocess',data={'opts':'1','exposure':'.5'},follow_redirects=False)
        self.assertEqual(r.status_code,303)
        self.assertEqual(main._photo_path(pid).read_bytes(),first)
        r=self.client.post(f'/admin/p/{pid}/reprocess',data={'opts':'1'},follow_redirects=False)
        self.assertEqual(r.status_code,303)
        neutral=P.process(self.source,auto_adjust=False,fix_shadows=False,even_bg=False,replace_bg=False)
        self.assertEqual(main._photo_path(pid).read_bytes(),neutral.jpeg)

    def test_invalid_manual_input_returns_bad_request(self):
        pid=self.upload()
        for value in ('nan','inf','2','nonsense'):
            r=self.client.post(f'/admin/p/{pid}/reprocess',data={'opts':'1','exposure':value})
            self.assertEqual(r.status_code,400)

    def test_small_source_can_be_prepared_and_printed_without_false_pass(self):
        b=io.BytesIO();Image.open(io.BytesIO(self.source)).resize((355,388)).save(b,'JPEG')
        with patch.object(P,'get_analyzer',side_effect=RuntimeError('No model available')):
            pid=self.upload(b.getvalue(),print_only='on',exposure='.4')
        self.assertTrue(main._photo_path(pid).exists())
        row=db.get(pid);self.assertFalse(row['ok']);self.assertIsNone(row['code'])
        self.assertTrue(any(c['key']=='resolution' and c['status']=='fail' for c in json.loads(row['checks'])))
        self.assertEqual(self.client.get(f'/admin/p/{pid}/sheet.jpg').status_code,200)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/save.jpg').status_code,200)

    def test_staff_can_issue_with_quality_failures_and_red_results_are_retained(self):
        pid=self.upload()
        with db.conn() as c:c.execute('UPDATE photos SET ok=0,checks=? WHERE id=?',(json.dumps([{'key':'sharp','label':'Focus','status':'fail','detail':'Known failure'}]),pid))
        self.assertEqual(self.issue(pid).status_code,400)
        r=self.issue(pid,staff_override='on',override_reason='Staff reviewed the source')
        self.assertEqual(r.status_code,303,r.text)
        row=db.get(pid);review=json.loads(row['issue_review'])
        self.assertEqual(review['decision'],'staff_override')
        self.assertIn('sharp',review['staff_override']['working_failed_checks'])
        self.assertFalse(row['ok'])
        self.assertTrue(any(c['status']=='fail' for c in json.loads(row['checks'])))
        self.assertTrue((config.PHOTO_DIR/(pid+'_source')).exists())
        self.assertIn('Issued under staff responsibility',self.client.get(f'/admin/p/{pid}').text)

    def test_new_final_failures_can_be_overridden_and_are_saved(self):
        pid=self.upload()
        failed=P.Result(False,[P.Check('shadow','Lighting','fail','Known final failure')])
        with patch.object(P,'check_code_photo',return_value=failed):
            r=self.issue(pid,staff_override='on')
        self.assertEqual(r.status_code,303,r.text)
        row=db.get(pid);review=json.loads(row['issue_review'])
        self.assertIn('shadow',review['staff_override']['final_failed_checks'])
        self.assertFalse(row['ok'])

    def test_full_frame_code_requires_acknowledgement_not_a_quality_pass(self):
        pid=self.upload(print_only='on')
        self.assertEqual(self.issue(pid).status_code,400)
        self.assertEqual(self.issue(pid,staff_override='on').status_code,303)
        self.assertTrue(json.loads(db.get(pid)['issue_review'])['staff_override']['full_frame_job'])

    def test_unavailable_quality_engine_is_recorded_and_staff_can_proceed(self):
        with patch.object(P,'get_analyzer',side_effect=RuntimeError('Model missing')):
            pid=self.upload(print_only='on')
            response=self.issue(pid,staff_override='on')
        self.assertEqual(response.status_code,303,response.text)
        review=json.loads(db.get(pid)['issue_review'])
        self.assertIn('quality_unavailable',review['staff_override']['final_failed_checks'])
        self.assertFalse(db.get(pid)['ok'])

    def test_print_preview_api_canvas_and_source_failures_are_retained(self):
        b=io.BytesIO();Image.new('RGB',(355,388),'grey').save(b,'JPEG');small=b.getvalue()
        response_image=io.BytesIO();Image.new('RGB',(1024,1120),'grey').save(response_image,'PNG')
        response=json.dumps({'data':[{'b64_json':base64.b64encode(response_image.getvalue()).decode()}]}).encode()
        class Reply(io.BytesIO):headers={}
        with patch.object(config,'OPENAI_API_KEY','test-key'),patch.object(ai_prepare.urllib.request,'urlopen',return_value=Reply(response)) as remote:
            ai_prepare.prepare(small,print_only=True)
        payload=json.loads(remote.call_args.args[0].data)
        width,height=map(int,payload['size'].split('x'))
        self.assertGreaterEqual(min(width,height),500)
        self.assertLessEqual(width*height,3_686_400)


if __name__=='__main__':unittest.main()
