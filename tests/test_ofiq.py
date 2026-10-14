"""Native-result validation and exact-file binding; fixtures never imply approval."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='ofiq-tests-'), ADMIN_PASSWORD='test-only',
                  HMPO_KEY_URL='', OPENAI_API_KEY='', OFIQ_ENABLED='false')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app import config, ofiq, processing, pipeline_status
from synthetic import Fake, make_face


def vector():
    return [dict(id=ident,name=name,raw=-2.0 if name=='HeadPoseYaw' else 1.,quality=90.,return_code=0)
            for ident,name in ofiq.MEASURES.items()]


class OfiqTests(unittest.TestCase):
    def test_complete_vector_retains_signed_raw_values_without_passes(self):
        rows,status=ofiq.validate_measurements(vector(),0)
        self.assertEqual(status,'completed'); self.assertEqual(len(rows),28)
        self.assertTrue(all(r['status']=='measured' for r in rows))
        self.assertEqual(next(r['raw'] for r in rows if r['name']=='HeadPoseYaw'),-2)

    def test_failed_native_code_missing_and_nonfinite_values_cannot_be_green(self):
        cases=[([],0),(vector(),11)]
        a=vector();a[0]['return_code']=1;cases.append((a,0))
        a=vector();a[0]['raw']=float('nan');cases.append((a,0))
        a=vector();a[0]['quality']=-1;cases.append((a,0))
        a=vector();a[0]['quality']=101;cases.append((a,0))
        for values,code in cases:
            rows,status=ofiq.validate_measurements(values,code)
            self.assertNotEqual(status,'completed');self.assertTrue(any(r['status']=='unavailable' for r in rows))
            json.dumps(rows,allow_nan=False)

    def test_duplicate_unknown_and_mislabeled_measures_are_rejected(self):
        for values in [[vector()[0]]*2,[dict(vector()[0],id=1)],[dict(vector()[0],name='Invented')],['invalid']]:
            with self.assertRaises(ValueError):ofiq.validate_measurements(values,0)

    def test_disabled_and_missing_runtime_never_claim_execution(self):
        with patch.object(config,'OFIQ_ENABLED',False):self.assertEqual(ofiq.assess({})['status'],'off')
        with patch.object(config,'OFIQ_ENABLED',True),patch.object(config,'OFIQ_RUNTIME_DIR',Path('/missing-ofiq')):
            self.assertEqual(ofiq.assess({})['status'],'unavailable')

    def test_pipeline_binds_exact_save_and_exact_delivery_bytes(self):
        data,analysis=make_face(W=1500,H=2000)
        def native(images):
            return dict(status='completed',stages=[dict(stage=k,image_sha256=hashlib.sha256(v).hexdigest()) for k,v in images.items()])
        with patch.object(config,'OFIQ_ENABLED',True),patch.object(ofiq,'assess',side_effect=native) as assess:
            result=processing.process(data,analyzer=Fake(analysis),country_id='united-kingdom-online-renewal')
            self.assertIsNotNone(result.jpeg)
            sent=assess.call_args.args[0]
            self.assertEqual(sent['save_jpeg'],processing.save_photo(result.jpeg,'united-kingdom-online-renewal'))
            final=sent['save_jpeg']
            processing.process(final,analyzer=Fake(analysis),country_id='united-kingdom-online-renewal',framed=True)
            self.assertEqual(assess.call_args.args[0],{'delivery_jpeg':final})

    def test_unavailable_ofiq_preserves_pixels_and_staff_override_behavior(self):
        data,analysis=make_face(W=1500,H=2000)
        with patch.object(config,'OFIQ_ENABLED',False):
            baseline=processing.process(data,analyzer=Fake(analysis))
        with patch.object(config,'OFIQ_ENABLED',True),patch.object(ofiq,'assess',return_value=dict(status='unavailable',stages=[])):
            result=processing.process(data,analyzer=Fake(analysis))
        self.assertEqual(result.jpeg,baseline.jpeg);self.assertEqual(result.ok,baseline.ok)
        self.assertEqual(next(c.status for c in result.checks if c.key=='ofiq_unavailable'),'warn')

    def test_source_orientation_is_baked_losslessly(self):
        image=Image.new('RGB',(40,60),(12,35,78));exif=image.getexif();exif[274]=6
        data=io.BytesIO();image.save(data,'JPEG',exif=exif)
        with Image.open(io.BytesIO(ofiq.source_png(data.getvalue()))) as output:
            self.assertEqual(output.size,(60,40));self.assertNotIn(274,output.getexif())

    @unittest.skipUnless(os.getenv('NATIVE_OFIQ_TESTS')=='1','Real native fixtures opt-in')
    def test_real_c_api_matches_the_official_fixture_table(self):
        import csv
        root=config.BASE_DIR/'output/ofiq-native/OFIQ-Project'
        with (root/'data/tests/expected_results/expected_results.csv').open() as table:
            expected=list(csv.DictReader(table,delimiter=';'))[0]
        file=root/'data/tests/images/b-01-smile.png'
        with patch.object(config,'OFIQ_ENABLED',True):result=ofiq.assess({'fixture':file.read_bytes()})
        self.assertEqual(result['status'],'completed')
        for row in result['stages'][0]['measurements']:
            self.assertLessEqual(abs(row['quality']-float(expected[row['name']+'.scalar'])),1.)
        self.assertEqual(result['stages'][0]['image_sha256'],hashlib.sha256(file.read_bytes()).hexdigest())


class OfiqRouteTests(unittest.TestCase):
    def setUp(self):
        import base64
        from starlette.testclient import TestClient
        from app import db, main
        self.db,self.main=db,main;db.init()
        self.client=TestClient(main.app,headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-only').decode()})
        data,an=make_face(W=1500,H=2000)
        with patch.object(config,'OFIQ_ENABLED',False),patch.object(processing,'get_analyzer',return_value=Fake(an)):
            reply=self.client.post('/admin/new',files={'photo':('test.jpg',data)},data={'opts':'1'},follow_redirects=False)
        self.url=reply.headers['location'];self.pid=self.url.rsplit('/',1)[-1]

    def test_measure_only_endpoint_is_private_revision_bound_and_preserves_pixels(self):
        from starlette.testclient import TestClient
        self.assertEqual(TestClient(self.main.app).post(self.url+'/ofiq').status_code,401)
        revision=self.db.get(self.pid)['revision'];photo=self.client.get(self.url+'/full.jpg').content
        self.assertEqual(self.client.post(self.url+'/ofiq',data={'review_revision':str(revision)}).status_code,503)
        def record(images):
            stages=[]
            for name,data in images.items():
                rows,status=ofiq.validate_measurements(vector(),0)
                with Image.open(io.BytesIO(data)) as im:size=list(im.size)
                stages.append(dict(stage=name,status=status,input_size=size,assessment_seconds=0,
                    image_sha256=hashlib.sha256(data).hexdigest(),return_code=0,measurements=rows))
            return dict(version=ofiq.VERSION,status='completed',stages=stages)
        with patch.object(config,'OFIQ_ENABLED',True),patch.object(ofiq,'assess',side_effect=record):
            reply=self.client.post(self.url+'/ofiq',data={'review_revision':str(revision)},follow_redirects=False)
            self.assertEqual(reply.status_code,303)
            self.assertEqual(self.client.post(self.url+'/ofiq',data={'review_revision':str(revision)}).status_code,409)
            page=self.client.get(self.url).text
        self.assertEqual(self.client.get(self.url+'/full.jpg').content,photo)
        self.assertIn('Mapped quality',page);self.assertIn('Exact Save JPEG',page)
        self.assertIn('source_file_sha256',json.loads(self.db.get(self.pid)['measurements'])['ofiq'])

    def test_out_of_band_file_change_cannot_attach_results_to_different_pixels(self):
        revision=self.db.get(self.pid)['revision']
        def change(images):
            self.main._photo_path(self.pid).write_bytes(b'changed')
            return dict(status='completed',stages=[])
        with patch.object(config,'OFIQ_ENABLED',True),patch.object(ofiq,'assess',side_effect=change):
            self.assertEqual(self.client.post(self.url+'/ofiq',data={'review_revision':str(revision)}).status_code,409)
        self.assertEqual(self.db.get(self.pid)['revision'],revision)


if __name__=='__main__':unittest.main()
