"""Authenticated reference-check workflow; no government requests or customer photos."""
import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='tuttocode-govuk-tests-'), ADMIN_PASSWORD='test-only',
                  OPENAI_API_KEY='', HMPO_KEY_URL='', GOVUK_PRECHECK_ENABLED='1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starlette.testclient import TestClient
from app import config, db, main, processing, govuk_precheck
from synthetic import Fake, make_face

logging.getLogger('httpx').setLevel(logging.WARNING)


class ButtonTests(unittest.TestCase):
    def setUp(self):
        db.init()
        with db.conn() as c:
            c.execute('DELETE FROM govuk_checks')
            c.execute('DELETE FROM photos')
        self.source, analysis = make_face()
        processing._analyzer = Fake(analysis)
        self.auth = {'Authorization': 'Basic ' + base64.b64encode(b'admin:test-only').decode()}
        self.client = TestClient(main.app, headers=self.auth)
        response = self.client.post('/admin/new', data={'opts': '1','country_id':'united-kingdom-online-renewal'},
                                    files={'photo': ('synthetic.jpg', self.source, 'image/jpeg')}, follow_redirects=False)
        self.path = response.headers['location']
        self.pid = self.path.rsplit('/',1)[-1]
        self.form = {'dob': '1980-01-01','synthetic_dob':'on','govuk_consent':'on','review_revision':'0'}

    async def fake_execute(self, pid, run_id):
        with db.conn() as c:
            c.execute("UPDATE govuk_checks SET status='good',result=? WHERE id=?", (json.dumps({
                'status':'good','resultText':'Photo result\nGood','elapsedSeconds':1,'uploaded':True,
                'referenceComparisonEligible':False}),run_id))

    def start(self, data=None):
        with patch.object(govuk_precheck,'execute',self.fake_execute):
            return self.client.post(self.path+'/govuk', data=data or self.form)

    def test_permission_dob_revision_country_and_setup_are_checked(self):
        for change, status in [({'govuk_consent':''},400),({'dob':'2001-02-29'},400),({'review_revision':'99'},409)]:
            response = self.start({**self.form, **change})
            self.assertEqual(response.status_code,status)
        with patch.object(config,'GOVUK_PRECHECK_ENABLED',False):
            self.assertEqual(self.start().status_code,503)
        with db.conn() as c:
            c.execute("UPDATE photos SET country_id='ireland-passport' WHERE id=?",(self.pid,))
        self.assertEqual(self.start().status_code,400)

    def test_exact_saved_jpeg_is_frozen_and_checks_remain_unchanged(self):
        before = db.get(self.pid)
        response = self.start()
        self.assertEqual(response.status_code,202)
        run = govuk_precheck.get_run(self.pid,response.json()['id'])
        frozen = (config.GOVUK_DIR/self.pid/run['id']/'input.jpg').read_bytes()
        expected = self.client.get(self.path+'/save.jpg').content
        self.assertEqual(frozen, expected)
        self.assertEqual(run['photo_sha256'],hashlib.sha256(expected).hexdigest())
        self.assertEqual(db.get(self.pid)['checks'],before['checks'])
        self.assertEqual(db.get(self.pid)['revision'],before['revision'])
        self.assertIsNone(db.get(self.pid)['code'])
        state = self.client.get(self.path+'/govuk').json()['runs'][0]
        self.assertTrue(state['current'])
        self.assertFalse(state['comparison_eligible'])
        self.assertTrue(state['synthetic_dob'])

    def test_result_is_stale_after_revision_or_untracked_file_change(self):
        self.start()
        file = config.PHOTO_DIR / f'{self.pid}.jpg'
        file.write_bytes(file.read_bytes()+b'changed')
        self.assertFalse(self.client.get(self.path+'/govuk').json()['runs'][0]['current'])
        with db.conn() as c:
            c.execute('UPDATE photos SET revision=revision+1 WHERE id=?',(self.pid,))
        self.assertFalse(self.client.get(self.path+'/govuk').json()['runs'][0]['current'])

    def test_authentication_and_expiry_protect_evidence(self):
        self.start()
        run = self.client.get(self.path+'/govuk').json()['runs'][0]
        file = config.GOVUK_DIR/self.pid/run['id']/'result.png'
        file.write_bytes(b'private screenshot')
        route=self.path+'/govuk/'+run['id']+'/result.png'
        input_route=self.path+'/govuk/'+run['id']+'/input.jpg'
        self.assertEqual(TestClient(main.app).get(route).status_code,401)
        self.assertEqual(TestClient(main.app).get(input_route).status_code,401)
        self.assertEqual(self.client.get(route).content,b'private screenshot')
        self.assertEqual(hashlib.sha256(self.client.get(input_route).content).hexdigest(),run['photo_sha256'])
        self.assertEqual(self.client.get(self.path+'/govuk/not-a-real-run/result.png').status_code,404)
        with db.conn() as c:
            c.execute('UPDATE photos SET expires=? WHERE id=?',(time.time()-1,self.pid))
        self.assertEqual(self.client.get(route).status_code,404)
        db.purge_expired()
        self.assertFalse(file.parent.exists())
        self.assertIsNone(govuk_precheck.get_run(self.pid,run['id']))

    def test_frozen_test_download_detects_tampering(self):
        response=self.start()
        run_id=response.json()['id']
        (config.GOVUK_DIR/self.pid/run_id/'input.jpg').write_bytes(b'changed')
        self.assertEqual(self.client.get(self.path+'/govuk/'+run_id+'/input.jpg').status_code,409)

    def test_interrupted_old_worker_becomes_unavailable_on_refresh(self):
        row=db.get(self.pid)
        master=(config.PHOTO_DIR/f'{self.pid}.jpg').read_bytes()
        run_id=govuk_precheck.start(row,master,processing.save_photo(master,row['country_id']),'1980-01-01',True)
        with db.conn() as c:
            c.execute('UPDATE govuk_checks SET created=? WHERE id=?',(time.time()-config.GOVUK_TIMEOUT_SECONDS-60,run_id))
        self.assertEqual(govuk_precheck.history(row,master)[0]['status'],'unavailable')

    def test_one_checker_at_a_time_and_no_duplicate_upload_start(self):
        row=db.get(self.pid)
        master=(config.PHOTO_DIR/f'{self.pid}.jpg').read_bytes()
        export=processing.save_photo(master,row['country_id'])
        govuk_precheck.start(row,master,export,'1980-01-01',True)
        with self.assertRaisesRegex(ValueError,'Another GOV.UK'):
            govuk_precheck.start(row,master,export,'1980-01-01',True)

    def test_issued_photo_can_be_checked_without_mutation(self):
        with db.conn() as c:
            c.execute("UPDATE photos SET status='issued',code='existing' WHERE id=?",(self.pid,))
        self.assertEqual(self.start().status_code,202)
        self.assertEqual(db.get(self.pid)['code'],'existing')
        self.assertEqual(db.get(self.pid)['status'],'issued')

    def test_worker_failure_is_unavailable_and_does_not_log_secrets(self):
        row=db.get(self.pid)
        master=(config.PHOTO_DIR/f'{self.pid}.jpg').read_bytes()
        run_id=govuk_precheck.start(row,master,processing.save_photo(master,row['country_id']),'1980-01-01',True)
        async def fail(*args,**kwargs):
            self.assertNotIn('OPENAI_API_KEY',kwargs['env'])
            self.assertNotIn('ADMIN_PASSWORD',kwargs['env'])
            self.assertNotIn('1980-01-01',args)
            raise RuntimeError('secret-provider-error')
        with patch('asyncio.create_subprocess_exec',fail):
            asyncio.run(govuk_precheck.execute(self.pid,run_id))
        result=govuk_precheck.history(row,master)[0]
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('secret-provider-error',result['error'])

    def test_button_and_separate_non_nested_form_are_rendered(self):
        page=self.client.get(self.path).text
        self.assertIn('id="open-govuk"',page)
        self.assertIn('id="govuk-form"',page)
        self.assertGreater(page.index('id="govuk-form"'),page.index('</form>'))

    def test_bot_diagnosis_is_exposed_separately_without_rewriting_the_result(self):
        response=self.start()
        run_id=response.json()['id']
        with db.conn() as c:
            c.execute("UPDATE govuk_checks SET status='unavailable',result=? WHERE id=?",(json.dumps({
                'status':'unavailable','error':'Browser blocked','errorCode':'known_bots_detection',
                'accessDiagnostics':{'category':'known_bots_detection','attackId':'20000051','messageId':'000000041021'},
                'referenceComparisonEligible':False}),run_id))
        record=self.client.get(self.path+'/govuk').json()['runs'][0]
        self.assertEqual(record['status'],'unavailable')
        self.assertEqual(record['error_code'],'known_bots_detection')
        self.assertEqual(record['access_diagnostics']['attackId'],'20000051')
        self.assertFalse(record['comparison_eligible'])


if __name__=='__main__':
    unittest.main(verbosity=2)
