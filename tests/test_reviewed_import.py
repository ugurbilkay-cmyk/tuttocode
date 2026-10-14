"""Exact JPEG delivery, staff evidence and isolation from preparation edits."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix='tuttocode-reviewed-import-'))
os.environ.update(DATA_DIR=str(ROOT), ADMIN_PASSWORD='test-only', OPENAI_API_KEY='',
                  HMPO_KEY_URL='', SHORT_DOMAIN='tpcode.uk', PUBLIC_UPLOADS='true', SMTP_HOST='')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jwt
import numpy as np
from PIL import Image
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient
from app import config, db, main, photomatic, processing, reviewed_import as R

UK = 'united-kingdom-online-renewal'


class ImportTests(unittest.TestCase):
    def setUp(self):
        db.init()
        self.client = TestClient(main.app, headers={'Authorization': 'Basic ' + base64.b64encode(b'admin:test-only').decode()})
        rgb = np.random.default_rng(6).integers(0, 256, (1120, 800, 3), dtype=np.uint8)
        buf = io.BytesIO(); Image.fromarray(rgb).save(buf, 'JPEG', quality=85, comment=b'Preserve this metadata')
        self.jpeg = buf.getvalue()
        self.digest = hashlib.sha256(self.jpeg).hexdigest()

    def upload(self, data=None, country=UK, **fields):
        return self.client.post('/admin/import', data={'country_id': country, 'age_group': 'adult',
            'portrait_confirmed': 'on', **fields}, files={'photo': ('portrait.jpg', data or self.jpeg, 'image/jpeg')}, follow_redirects=False)

    def imported(self, **fields):
        response = self.upload(**fields)
        self.assertEqual(response.status_code, 303, response.text)
        return response.headers['location'].rsplit('/', 1)[1]

    def form(self, pid, **fields):
        row = db.get(pid)
        return {'review_revision': str(row['revision']), 'photo_sha256': self.digest,
                'operator': 'Test operator', 'vendor_profile': 'United Kingdom Online Renewal',
                **{key: 'on' for key in ['review_export', 'review_document', 'review_likeness', 'review_visibility', 'customer_permission']},
                **{'group_' + key: 'pass' for key, _ in R.GROUPS}, **fields}

    def review(self, pid, **fields):
        response = self.client.post(f'/admin/p/{pid}/external-review', data=self.form(pid, **fields), follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)

    def issue(self, pid, **fields):
        row = db.get(pid)
        return self.client.post(f'/admin/p/{pid}/issue', data={
            'review_revision': str(row['revision']), 'photo_sha256': self.digest,
            'issue_reviewed_export': 'on', **fields}, follow_redirects=False)

    def test_import_save_and_preview_keep_exact_jpeg_without_preparation(self):
        with patch.object(processing, 'process', side_effect=AssertionError('Must not prepare export')):
            pid = self.imported()
        self.assertEqual((config.PHOTO_DIR / f'{pid}.jpg').read_bytes(), self.jpeg)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/save.jpg').content, self.jpeg)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/full.jpg').content, self.jpeg)
        record = json.loads(db.get(pid)['external_review'])
        self.assertEqual(record['file']['sha256'], self.digest)
        self.assertFalse(record['reviewed']); self.assertFalse(db.get(pid)['ok'])
        self.assertTrue(all(m['status'] == 'not_tested' and m['value'] == '' for m in record['metrics'].values()))
        page = self.client.get(f'/admin/p/{pid}').text
        self.assertIn('Not tested', page); self.assertIn('Save staff review', page)
        self.assertNotIn('Issue UK code from exact JPEG', page)

    def test_non_jpeg_truncated_and_oversized_files_rejected_without_jobs(self):
        before = len(db.recent())
        buf = io.BytesIO(); Image.new('RGB', (800, 1120)).save(buf, 'PNG')
        for data in (buf.getvalue(), self.jpeg[:200], b'not a photo'):
            self.assertEqual(self.upload(data).status_code, 400)
        with patch.object(config, 'MAX_UPLOAD_MB', 0):
            self.assertEqual(self.upload().status_code, 413)
        self.assertEqual(len(db.recent()), before)

    def test_staff_auth_and_origin_checks_and_no_public_review_access(self):
        self.assertEqual(self.client.get('/admin/import', headers={'Authorization': ''}).status_code, 401)
        self.assertEqual(self.client.post('/admin/import', headers={'Origin': 'https://another.example'}).status_code, 403)
        pid = self.imported()
        for path in (f'/admin/p/{pid}', f'/admin/p/{pid}/full.jpg', f'/admin/p/{pid}/save.jpg'):
            self.assertEqual(self.client.get(path, headers={'Authorization': ''}).status_code, 401)
        for path in (f'/r/{pid}', f'/r/{pid}/preview.jpg'):
            self.assertEqual(self.client.get(path, headers={'Authorization': ''}).status_code, 404)

    def test_complete_review_preserves_vendor_values_and_untested_fields(self):
        pid = self.imported()
        self.review(pid, metric_hotspots='59', status_hotspots='caution', metric_expression='-1')
        record = json.loads(db.get(pid)['external_review'])
        self.assertEqual(record['metrics']['hotspots'], {'value': '59', 'status': 'caution'})
        self.assertEqual(record['metrics']['expression'], {'value': '-1', 'status': 'not_tested'})
        self.assertEqual(record['account'], 'admin'); self.assertEqual(record['operator'], 'Test operator')
        self.assertEqual(record['review_revision'], db.get(pid)['revision'])
        self.assertEqual(record['evidence_source'], 'staff_attested_photomatic')

    def test_missing_confirmations_operator_and_invalid_status_do_not_save_review(self):
        pid = self.imported(); revision = db.get(pid)['revision']
        for fields in ({'operator': ''}, {'customer_permission': ''}, {'group_geometry': 'green'},
                       {'status_hotspots': 'automatic'}, {'metric_hotspots': 'x' * 101}):
            response = self.client.post(f'/admin/p/{pid}/external-review', data=self.form(pid, **fields))
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(db.get(pid)['revision'], revision)

    def test_stale_review_and_wrong_hash_cannot_approve_or_issue(self):
        pid = self.imported(); old = self.form(pid)
        self.review(pid)
        self.assertEqual(self.client.post(f'/admin/p/{pid}/external-review', data=old).status_code, 409)
        self.assertEqual(self.issue(pid, review_revision=old['review_revision']).status_code, 409)
        self.assertEqual(self.issue(pid, photo_sha256='0' * 64).status_code, 409)

    def test_red_and_unknown_categories_allow_responsibility_without_turning_green(self):
        pid = self.imported()
        self.review(pid, group_image_quality='fail', group_background='not_tested', status_hotspots='fail', metric_hotspots='12')
        self.assertEqual(self.issue(pid).status_code, 400)
        with patch.object(processing, 'code_photo', side_effect=AssertionError('Must not reencode')):
            self.assertEqual(self.issue(pid, staff_override='on', override_reason='Staff decision').status_code, 303)
        row = db.get(pid); review = json.loads(row['issue_review'])
        self.assertEqual(review['external_review']['groups']['image_quality'], 'fail')
        self.assertEqual(review['staff_override']['unmeasured_groups'], ['background'])
        self.assertIn('photomatic_hotspots', review['staff_override']['failed_checks'])

    def test_technical_quality_failures_are_advisory_but_bytes_unchanged(self):
        buf = io.BytesIO(); Image.new('RGB', (355, 388), 'grey').save(buf, 'JPEG')
        self.jpeg = buf.getvalue(); self.digest = hashlib.sha256(self.jpeg).hexdigest()
        pid = self.imported(); self.review(pid)
        self.assertEqual(self.issue(pid).status_code, 400)
        self.assertEqual(self.issue(pid, staff_override='on').status_code, 303)
        self.assertEqual((config.PHOTO_DIR / f'{pid}_code.jpg').read_bytes(), self.jpeg)

    def test_signed_retrieval_returns_exact_import_and_rejects_tampering(self):
        pid = self.imported(); self.review(pid)
        self.assertEqual(self.issue(pid).status_code, 303)
        row = db.get(pid); code = row['code']
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode({'sub': f'https://tpcode.uk/{code}', 'iat': int(time.time())}, key, algorithm='RS256')
        url = f'https://tpcode.uk/{code}'
        with patch.object(main.hmpo_auth, 'get_key', return_value=key.public_key()):
            self.assertEqual(self.client.get(url, headers={'Authorization': ''}).status_code, 404)
            response = self.client.get(url, headers={'Authorization': 'Bearer ' + token})
            self.assertEqual(response.status_code, 200); self.assertEqual(response.content, self.jpeg)
            (config.PHOTO_DIR / f'{pid}_code.jpg').write_bytes(self.jpeg + b'changed')
            self.assertEqual(self.client.get(url, headers={'Authorization': token}).status_code, 404)
        self.assertEqual(json.loads(row['issue_review'])['photo_sha256'], self.digest)

    def test_no_code_without_recorded_review_and_non_uk_keeps_provider_route(self):
        pid = self.imported(); self.assertEqual(self.issue(pid, staff_override='on').status_code, 409)
        ireland = next(p['id'] for p in photomatic.COUNTRIES.values() if p['code_service'] == 'ie')
        response = self.upload(country=ireland); pid = response.headers['location'].rsplit('/', 1)[1]
        self.assertEqual(self.issue(pid).status_code, 503)
        self.assertIn('external provider', self.client.get(f'/admin/p/{pid}').text)

    def test_preparation_edit_paths_cannot_modify_a_preserved_export(self):
        pid = self.imported()
        (config.PHOTO_DIR / f'{pid}_source').write_bytes(self.jpeg)
        with patch.object(processing, 'process', side_effect=AssertionError('Must not edit imported export')):
            for path, data in [('reprocess', {'country_id': UK}), ('restore-original', {}),
                               ('ai/accept', {'review_likeness': 'on'})]:
                response = self.client.post(f'/admin/p/{pid}/{path}', data=data)
                self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((config.PHOTO_DIR / f'{pid}.jpg').read_bytes(), self.jpeg)

    def test_linked_preparation_snapshot_and_original_retention(self):
        profile = photomatic.country(UK); parent = db.new_id()
        result = processing.Result(True, [], self.jpeg, R.preview(self.jpeg))
        main._store_result(parent, result)
        (config.PHOTO_DIR / f'{parent}_source').write_bytes(b'original-camera-evidence')
        db.create(parent, 'shop', 'adult', result, country_id=UK, options={'auto_adjust': False})
        response = self.client.get(f'/admin/p/{parent}/photomatic.jpg')
        self.assertEqual(response.content, self.jpeg); self.assertEqual(response.headers['x-photo-sha256'], self.digest)
        self.assertEqual(self.upload(parent_id=parent, parent_revision='-1').status_code, 409)
        pid = self.imported(parent_id=parent, parent_revision=str(db.get(parent)['revision']))
        record = json.loads(db.get(pid)['external_review'])
        self.assertEqual(record['parent']['prepared_sha256'], self.digest)
        self.assertEqual((config.PHOTO_DIR / f'{pid}_source').read_bytes(), b'original-camera-evidence')
        self.review(pid); self.assertEqual(self.issue(pid).status_code, 303)
        self.assertTrue((config.PHOTO_DIR / f'{pid}_source').exists())

    def test_file_change_and_expiry_disable_view_save_review_and_cleanup(self):
        pid = self.imported(); self.review(pid)
        path = config.PHOTO_DIR / f'{pid}.jpg'; path.write_bytes(self.jpeg + b'changed')
        self.assertEqual(self.issue(pid).status_code, 409)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/save.jpg').status_code, 409)
        path.write_bytes(self.jpeg)
        with db.conn() as c: c.execute('UPDATE photos SET expires=? WHERE id=?', (time.time() - 1, pid))
        for endpoint in ('', '/full.jpg', '/save.jpg'):
            self.assertEqual(self.client.get(f'/admin/p/{pid}{endpoint}').status_code, 404)
        db.purge_expired(); self.assertFalse(path.exists()); self.assertIsNone(db.get(pid))

    def test_email_attachment_is_exact_import_without_actual_sending(self):
        pid = self.imported(email='test@example.invalid'); sent = []
        class SMTP:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def starttls(self): pass
            def send_message(self, message): sent.append(message)
        with patch.object(config, 'SMTP_HOST', 'test.invalid'), patch.object(main.smtplib, 'SMTP', SMTP):
            self.assertTrue(main._email_photo(db.get(pid)))
        attachment = list(sent[0].iter_attachments())[0]
        self.assertEqual(attachment.get_payload(decode=True), self.jpeg)

    def test_issued_review_is_read_only_and_reissue_is_idempotent(self):
        pid = self.imported(); self.review(pid); self.assertEqual(self.issue(pid).status_code, 303)
        code = db.get(pid)['code']; revision = db.get(pid)['revision']
        self.assertEqual(self.issue(pid).status_code, 303); self.assertEqual(db.get(pid)['code'], code)
        self.assertEqual(self.client.post(f'/admin/p/{pid}/external-review', data=self.form(pid)).status_code, 409)
        self.assertEqual(db.get(pid)['revision'], revision)
        page = self.client.get(f'/admin/p/{pid}').text
        self.assertNotIn('Save staff review</button>', page)

    def test_linked_low_resolution_evidence_remains_visible_after_large_export(self):
        parent = db.new_id(); profile = photomatic.country(UK)
        checks = [processing.Check('resolution', 'Original detail', 'fail', 'Original capture is too small')]
        result = processing.Result(False, checks, self.jpeg, R.preview(self.jpeg))
        main._store_result(parent, result)
        db.create(parent, 'shop', 'adult', result, country_id=UK)
        pid = self.imported(parent_id=parent, parent_revision=str(db.get(parent)['revision']))
        self.review(pid)
        self.assertIn('Original capture is too small', self.client.get(f'/admin/p/{pid}').text)
        self.assertEqual(self.issue(pid).status_code, 400)
        self.assertEqual(self.issue(pid, staff_override='on').status_code, 303)
        review = json.loads(db.get(pid)['issue_review'])
        self.assertIn('source_resolution', review['staff_override']['failed_checks'])

    def test_concurrent_review_is_rejected_and_review_text_is_escaped(self):
        pid = self.imported(); token = db.claim_edit(pid)
        try:
            self.assertEqual(self.client.post(f'/admin/p/{pid}/external-review', data=self.form(pid)).status_code, 409)
            self.assertEqual(self.client.get(f'/admin/p/{pid}/photomatic.jpg').status_code, 409)
        finally:
            db.release_edit(pid, token)
        self.review(pid, review_notes='<script>alert("x")</script>')
        page = self.client.get(f'/admin/p/{pid}').text
        self.assertIn('&lt;script&gt;', page); self.assertNotIn('<script>alert("x")</script>', page)

    def test_exif_rotation_is_preserved_and_preview_orientation_matches(self):
        buf = io.BytesIO(); exif = Image.Exif(); exif[274] = 6
        Image.new('RGB', (1120, 800), 'tan').save(buf, 'JPEG', exif=exif)
        self.jpeg = buf.getvalue(); self.digest = hashlib.sha256(self.jpeg).hexdigest()
        pid = self.imported()
        record = json.loads(db.get(pid)['external_review'])
        self.assertEqual(record['file']['display_size'], [800, 1120])
        self.assertEqual(record['file']['encoded_size'], [1120, 800])
        self.assertEqual(record['file']['exif_orientation'], 6)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/save.jpg').content, self.jpeg)
        with Image.open(config.PHOTO_DIR / f'{pid}_prev.jpg') as image:
            self.assertLess(image.width, image.height)
        self.review(pid); self.assertEqual(self.issue(pid, staff_override='on').status_code, 303)


if __name__ == '__main__':
    unittest.main()
