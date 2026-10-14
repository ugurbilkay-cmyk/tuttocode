"""Frozen test inputs, manual observations, deduplication and private evidence."""
import base64
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='tuttocode-test-queue-'),ADMIN_PASSWORD='test-only',
                  OPENAI_API_KEY='',HMPO_KEY_URL='',GOVUK_PRECHECK_ENABLED='0')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from starlette.testclient import TestClient
from app import config,db,main,processing,test_queue
from synthetic import Fake,make_face
logging.getLogger('httpx').setLevel(logging.WARNING)


class QueueTests(unittest.TestCase):
    def setUp(self):
        db.init()
        with db.conn() as c:
            for table in ('test_observations','test_cases','test_queues','govuk_checks','photos'):c.execute(f'DELETE FROM {table}')
        self.data,analysis=make_face();processing._analyzer=Fake(analysis)
        self.client=TestClient(main.app,headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-only').decode()})
        self.pid=self.upload()
        png=io.BytesIO();Image.new('RGB',(80,50),'green').save(png,'PNG');self.shot=png.getvalue()

    def upload(self):
        r=self.client.post('/admin/new',data={'opts':'1','country_id':'united-kingdom-online-renewal'},
            files={'photo':('synthetic.jpg',self.data,'image/jpeg')},follow_redirects=False)
        self.assertEqual(r.status_code,303)
        return r.headers['location'].rsplit('/',1)[-1]

    def create(self,ids=None,retain=False):
        r=self.client.post('/admin/tests',data={'title':'Synthetic test queue','photo_ids':ids or [self.pid],
            'keep_snapshots':'on' if retain else ''},follow_redirects=False)
        self.assertEqual(r.status_code,303,r.text)
        self.url=r.headers['location'];self.qid=self.url.rsplit('/',1)[-1]
        self.item=test_queue.cases(self.qid)[0];self.case=self.url+'/cases/'+self.item['id']
        return r

    def observation(self,**changes):
        item=test_queue.case(self.qid,self.item['id'])
        return {'photo_sha256':json.loads(item['snapshot'])['sha256'],'observation_revision':str(item['observation_revision']),
                'gov_status':'good','dob':'1980-01-01','synthetic_dob':'on','same_file':'on',
                'image_quality':'dark_green','geometry':'dark_green','background':'dark_green',
                'comparable_framing':'on',**changes}

    def test_no_remote_calls_exact_save_export_and_snapshot_survives_edit(self):
        with patch('asyncio.create_subprocess_exec',side_effect=AssertionError('No browser should start')):
            self.create()
        saved=self.client.get(f'/admin/p/{self.pid}/save.jpg').content
        frozen=self.client.get(self.case+'/input.jpg').content
        self.assertEqual(saved,frozen)
        (config.PHOTO_DIR/f'{self.pid}.jpg').write_bytes(b'changed source job')
        self.assertEqual(self.client.get(self.case+'/input.jpg').content,frozen)
        self.assertIsNone(db.get(self.pid)['code'])
        self.assertEqual(self.client.get(self.case).status_code,200)

    def test_manual_result_preserves_exact_colours_and_sample_not_counted(self):
        self.create()
        r=self.client.post(self.case,data=self.observation(geometry='light_green'),follow_redirects=False)
        self.assertEqual(r.status_code,303)
        stats=test_queue.summary(test_queue.cases(self.qid))
        self.assertEqual(stats['gov_good'],1)
        self.assertEqual(stats['photomatic_dark_green'],0)
        self.client.post(self.case,data=self.observation(),follow_redirects=False)
        report=self.client.get(self.url+'/report.json').json()
        self.assertEqual(len(report['observation_history']),2)
        self.assertEqual(report['observation_history'][0]['observation']['photomatic_colours']['geometry'],'light_green')
        self.assertEqual(report['observation_history'][1]['observation']['photomatic_colours']['geometry'],'dark_green')
        stats=test_queue.summary(test_queue.cases(self.qid))
        self.assertEqual(stats['photomatic_dark_green'],1)
        self.assertEqual(stats['unique_customer_matches'],0)
        with db.conn() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM test_observations').fetchone()[0],2)

    def test_save_and_next_and_jpeg_bundle_names_match_manifest(self):
        other=self.upload();self.create([self.pid,other])
        r=self.client.post(self.case,data=self.observation(advance='yes'),follow_redirects=False)
        following=test_queue.cases(self.qid)[1]
        self.assertEqual(r.headers['location'],self.url+'/cases/'+following['id'])
        z=zipfile.ZipFile(io.BytesIO(self.client.get(self.url+'/bundle.zip').content))
        manifest=json.loads(z.read('manifest.json'))
        for case in manifest['cases']:
            photo=z.read(f'{case["position"]:03d}-{case["id"]}.jpg')
            self.assertEqual(hashlib.sha256(photo).hexdigest(),case['snapshot']['sha256'])

    def test_confirmation_dob_hash_stale_and_bad_colour(self):
        self.create()
        for changes in ({'same_file':''},{'dob':'2001-02-29'},{'photo_sha256':'other'},{'image_quality':'green'}, {'observation_revision':'99'}):
            self.assertEqual(self.client.post(self.case,data=self.observation(**changes)).status_code,400)
        self.assertEqual(test_queue.summary(test_queue.cases(self.qid))['pending'],1)

    def test_evidence_is_preserved_private_and_duplicates_count_once(self):
        other=self.upload();self.create([self.pid,other])
        for item in test_queue.cases(self.qid):
            self.item=item;self.case=self.url+'/cases/'+item['id']
            data=self.observation(synthetic_dob='',real_customer='on',customer_ref='C001')
            r=self.client.post(self.case,data=data,files={'photomatic_screenshot':('evidence.png',self.shot,'image/png')})
            self.assertEqual(r.status_code,200)
            self.assertEqual(self.client.get(self.case+'/photomatic').content,self.shot)
            self.assertEqual(TestClient(main.app).get(self.case+'/photomatic').status_code,401)
        stats=test_queue.summary(test_queue.cases(self.qid))
        self.assertEqual(stats['photomatic_dark_green'],2)
        self.assertEqual(stats['unique_customer_matches'],1)
        archive=zipfile.ZipFile(io.BytesIO(self.client.get(self.url+'/bundle.zip').content))
        for entry in json.loads(archive.read('manifest.json'))['observation_history']:
            info=entry['observation']['assets']['photomatic']
            self.assertEqual(archive.read(f'evidence/{entry["case_id"]}/{info["file"]}'),self.shot)

    def test_vendor_dark_green_does_not_hide_engine_or_government_flags(self):
        self.create()
        snapshot=json.loads(self.item['snapshot'])
        snapshot['engine_groups']=[{'name':'Face size and position','status':'fail'}]
        with db.conn() as c:
            c.execute('UPDATE test_cases SET snapshot=? WHERE id=?',(json.dumps(snapshot),self.item['id']))
        self.client.post(self.case,data=self.observation(gov_status='flagged'))
        stats=test_queue.summary(test_queue.cases(self.qid))
        self.assertEqual(stats['photomatic_dark_green'],1)
        self.assertEqual(stats['engine_vendor_disagreements'],1)
        self.assertEqual(stats['gov_vendor_disagreements'],1)

    def test_same_job_append_deduplicates_and_failed_create_rolls_back(self):
        self.create()
        r=self.client.post('/admin/tests',data={'queue_id':self.qid,'photo_ids':[self.pid]},follow_redirects=False)
        self.assertEqual(r.status_code,303);self.assertEqual(len(test_queue.cases(self.qid)),1)
        with db.conn() as c:before=c.execute('SELECT COUNT(*) FROM test_queues').fetchone()[0]
        r=self.client.post('/admin/tests',data={'photo_ids':[self.pid,'NotExistingPhoto123']})
        self.assertEqual(r.status_code,409)
        with db.conn() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM test_queues').fetchone()[0],before)

    def test_tampering_and_rejection_remove_study_copies(self):
        self.create(retain=True)
        file=config.TEST_QUEUE_DIR/self.qid/self.item['id']/'input.jpg'
        original=file.read_bytes();file.write_bytes(b'changed')
        self.assertEqual(self.client.get(self.case+'/input.jpg').status_code,404)
        self.assertEqual(self.client.get(self.url+'/bundle.zip').status_code,409)
        file.write_bytes(original)
        db.reject(self.pid);db.purge_expired()
        self.assertFalse(file.exists())
        self.assertEqual(json.loads(test_queue.case(self.qid,self.item['id'])['snapshot']),{})

    def test_retention_requires_choice_and_purge_honours_study_expiry(self):
        self.create(retain=True)
        file=config.TEST_QUEUE_DIR/self.qid/self.item['id']/'input.jpg'
        with db.conn() as c:c.execute('UPDATE photos SET expires=? WHERE id=?',(time.time()-1,self.pid))
        db.purge_expired();self.assertTrue(file.exists())
        with db.conn() as c:c.execute('UPDATE test_queues SET expires=? WHERE id=?',(time.time()-1,self.qid))
        db.purge_expired();self.assertFalse(file.exists())
        self.assertIsNone(test_queue.get(self.qid))

    def test_source_expiry_without_retention_scrubs_notes_and_images(self):
        self.create()
        self.client.post(self.case,data=self.observation(gov_feedback='Private test feedback'))
        with db.conn() as c:c.execute('UPDATE photos SET expires=? WHERE id=?',(time.time()-1,self.pid))
        db.purge_expired()
        row=test_queue.case(self.qid,self.item['id'])
        self.assertEqual(json.loads(row['observation']),{})
        self.assertEqual(self.client.get(self.case+'/input.jpg').status_code,404)
        self.assertEqual(self.client.get(self.case).status_code,200)
        self.assertEqual(self.client.post(self.case,data={}).status_code,410)


if __name__=='__main__':unittest.main(verbosity=2)
