"""Same-grid source comparison, honest zero-edit status and private originals."""
import base64,hashlib,io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='tuttocode-comparison-'),ADMIN_PASSWORD='test-only',OPENAI_API_KEY='',HMPO_KEY_URL='',OFIQ_ENABLED='false')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from starlette.testclient import TestClient
from app import processing as P,main,db,config,comparison,enhancement
from synthetic import Fake,make_face

class ComparisonTests(unittest.TestCase):
 def setUp(self):
  self.data,self.analysis=make_face()
  P._analyzer=Fake(self.analysis);db.init()
  self.client=TestClient(main.app,headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-only').decode()})
  self.opts=dict(auto_adjust=False,fix_shadows=False,even_bg=False,replace_bg=False)
 def process(self,**extra):
  return P.process(self.data,analyzer=P._analyzer,**dict(self.opts,**extra))
 def store(self,result,options=None):
  pid=db.new_id();main._store_result(pid,result)
  (config.PHOTO_DIR/(pid+'_source')).write_bytes(self.data)
  db.create(pid,'shop','adult',result,options=options or self.opts)
  return pid
 def test_unedited_same_grid_is_identical_and_never_a_thumbnail(self):
  r=self.process()
  self.assertIsNotNone(r.jpeg);self.assertEqual(r.before_jpeg,r.jpeg)
  self.assertEqual(comparison.size(r.before_jpeg),comparison.size(r.jpeg))
  self.assertGreater(comparison.size(r.before_jpeg)[0],350)
  self.assertEqual(r.measurements['comparison']['source_file_sha256'],hashlib.sha256(self.data).hexdigest())
 def test_exposure_changes_after_while_before_stays_the_original_grid(self):
  original=self.process();r=self.process(adjustments={'exposure':.4})
  self.assertEqual(r.before_jpeg,original.jpeg);self.assertNotEqual(r.jpeg,r.before_jpeg)
 def test_manual_crop_rotation_are_reconstructed_without_analysis_or_enhancement(self):
  crop=dict(zoom=1.15,x=2,y=2,rotation=0,angle=-2)
  r=self.process(crop=crop);self.assertIsNotNone(r.jpeg)
  with patch.object(P,'get_analyzer',side_effect=AssertionError('No model needed')),patch.object(enhancement,'apply',side_effect=AssertionError('No enhancement needed')):
   b=comparison.render(self.data,r.measurements,{'crop':crop},comparison.size(r.jpeg),None)
  self.assertEqual(b,r.before_jpeg);self.assertEqual(b,r.jpeg)
 def test_full_frame_has_matched_dimensions_and_no_edit_has_identical_bytes(self):
  r=self.process(print_only=True)
  self.assertEqual(r.before_jpeg,r.jpeg)
  self.assertEqual(comparison.size(r.before_jpeg),comparison.size(r.jpeg))
 def test_legacy_thumbnail_is_rebuilt_from_source_without_models_or_saved_pixel_changes(self):
  r=self.process();r.measurements.pop('comparison');pid=self.store(r)
  thumbnail=P._small_jpeg(P.load_image(self.data));path=config.PHOTO_DIR/(pid+'_before.jpg');path.write_bytes(thumbnail)
  master=main._photo_path(pid).read_bytes();revision=db.get(pid)['revision']
  with patch.object(P,'get_analyzer',side_effect=AssertionError('No analysis')),patch.object(enhancement,'apply',side_effect=AssertionError('No enhancement')):
   reply=self.client.get(f'/admin/p/{pid}/before.jpg')
  self.assertEqual(reply.status_code,200);self.assertEqual(reply.content,master)
  self.assertEqual(reply.headers['x-comparison-grid'],'1050x1350')
  self.assertEqual(path.read_bytes(),thumbnail);self.assertEqual(main._photo_path(pid).read_bytes(),master)
  self.assertEqual(db.get(pid)['revision'],revision)
 def test_comparison_revision_and_tampered_files_fail_closed(self):
  r=self.process();pid=self.store(r)
  for route in ('before.jpg','full.jpg'):
   self.assertEqual(self.client.get(f'/admin/p/{pid}/{route}?revision=999').status_code,409)
  (config.PHOTO_DIR/(pid+'_before.jpg')).write_bytes(b'changed')
  self.assertEqual(self.client.get(f'/admin/p/{pid}/before.jpg').status_code,409)
 def test_original_download_is_byte_exact_private_and_expired_jobs_are_unavailable(self):
  pid=self.store(self.process());url=f'/admin/p/{pid}/camera-original'
  self.assertEqual(TestClient(main.app).get(url).status_code,401)
  reply=self.client.get(url);self.assertEqual(reply.status_code,200);self.assertEqual(reply.content,self.data)
  self.assertIn('attachment',reply.headers['content-disposition'])
  with db.conn() as c:c.execute('UPDATE photos SET expires=0 WHERE id=?',(pid,))
  self.assertEqual(self.client.get(url).status_code,404)
  self.assertEqual(self.client.get(f'/admin/p/{pid}/before.jpg').status_code,404)
 def test_missing_legacy_geometry_and_source_hash_mismatch_do_not_display_thumbnail(self):
  r=self.process();r.measurements.pop('comparison');r.measurements.pop('crop_geometry');pid=self.store(r)
  self.assertEqual(self.client.get(f'/admin/p/{pid}/before.jpg').status_code,409)
  r=self.process();r.measurements.pop('comparison');r.measurements['ofiq']={'source_file_sha256':'0'*64};pid=self.store(r)
  self.assertEqual(self.client.get(f'/admin/p/{pid}/before.jpg').status_code,409)
 def test_accepted_ai_input_is_distinguished_from_untouched_camera_download(self):
  rgb=P.load_image(self.data);rgb=(rgb*.9).astype('uint8');buf=io.BytesIO();Image.fromarray(rgb).save(buf,'PNG');working=buf.getvalue()
  r=P.process(working,analyzer=P._analyzer,**self.opts)
  pid=self.store(r,dict(self.opts,ai={'model':'synthetic-test'}))
  (config.PHOTO_DIR/(pid+'_working_source')).write_bytes(working)
  reply=self.client.get(f'/admin/p/{pid}/before.jpg')
  self.assertEqual(reply.status_code,200);self.assertEqual(reply.headers['x-comparison-reference'],'working_source')
  self.assertEqual(reply.content,r.before_jpeg)
  self.assertEqual(self.client.get(f'/admin/p/{pid}/camera-original').content,self.data)

if __name__=='__main__':unittest.main()
