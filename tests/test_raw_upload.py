"""RAW upload boundaries and settings persist without decoding private fixtures."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='tuttocode-raw-upload-'),
                  ADMIN_PASSWORD='test-only', OPENAI_API_KEY='', HMPO_KEY_URL='', OFIQ_ENABLED='false')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starlette.exceptions import HTTPException
from starlette.testclient import TestClient
from app import config, db, main, processing as P, raw_development as R
from synthetic import Fake, make_face

RAW_HEADER = b'II*\x00\x10\x00\x00\x00CR\x02\x00\x00\x00\x00\x00'
RAW_SETTINGS = dict(wb='auto', exposure_ev=1.95, tone='photographic')


class RawUploadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tuttocode-raw-upload-case-')
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        photos = folder / 'photos'
        photos.mkdir()
        for key, value in dict(DATA_DIR=folder, PHOTO_DIR=photos, DB_PATH=folder / 'test.sqlite3',
                               ADMIN_USER='admin', ADMIN_PASSWORD='test-only', OPENAI_API_KEY='',
                               OFIQ_ENABLED=False).items():
            self.enterContext(patch.object(config, key, value))
        self.jpeg, analysis = make_face()
        P._analyzer = Fake(analysis)
        self.result = P.process(self.jpeg, analyzer=P._analyzer,
                                auto_adjust=False, fix_shadows=False, even_bg=False, replace_bg=False)
        self.raw = RAW_HEADER + b'synthetic container for route tests only'
        db.init()
        auth = 'Basic ' + base64.b64encode(b'admin:test-only').decode()
        self.client = TestClient(main.app, headers={'Authorization': auth})

    def store(self, options=None, country='united-kingdom-passport'):
        pid = db.new_id()
        main._store_result(pid, self.result)
        (config.PHOTO_DIR / f'{pid}_source').write_bytes(self.raw)
        db.create(pid, 'shop', 'adult', self.result, country_id=country,
                  options=options or {'raw_settings': RAW_SETTINGS})
        return pid

    def test_raw_limit_uses_signature_and_retains_exact_original(self):
        data = RAW_HEADER + bytes(1024 * 1024 + 12)
        with patch.object(config, 'MAX_UPLOAD_MB', 1), patch.object(config, 'MAX_RAW_UPLOAD_MB', 2), \
                patch.object(P, 'process', return_value=self.result) as process:
            response = self.client.post('/admin/new', files={'photo': ('camera.jpg', data)},
                                        data={'opts': '1'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(process.call_args.kwargs['raw_settings'],
                         dict(wb='camera', exposure_ev=0., tone='neutral'))
        pid = response.headers['location'].rsplit('/', 1)[-1]
        self.assertEqual((config.PHOTO_DIR / f'{pid}_source').read_bytes(), data)
        self.assertIn('raw_settings', json.loads(db.get(pid)['options']))

    def test_raw_and_ordinary_limits_are_independent_of_extension(self):
        with patch.object(config, 'MAX_UPLOAD_MB', 1), patch.object(config, 'MAX_RAW_UPLOAD_MB', 2), \
                patch.object(P, 'process') as process:
            fake = self.client.post('/admin/new', files={'photo': ('fake.cr2', bytes(1024 * 1024 + 1))})
            raw = self.client.post('/admin/new', files={'photo': ('real.cr2', RAW_HEADER + bytes(2 * 1024 * 1024))})
        self.assertEqual(fake.status_code, 413)
        self.assertEqual(raw.status_code, 413)
        process.assert_not_called()

    def test_raw_controls_validate_then_do_not_change_jpeg_options(self):
        form = dict(opts='1', raw_wb='auto', raw_exposure_ev='1.95', raw_tone='photographic',
                    adaptive_profile='balanced')
        options = main._opts(form)
        self.assertEqual(options['raw_settings'], RAW_SETTINGS)
        for key in ('denoise', 'skin', 'blemish'):
            self.assertEqual(options['enhancement_options'][key], 0)
        self.assertEqual(options['enhancement_options']['adaptive_profile'], 'balanced')
        self.assertNotIn('raw_settings', main._raw_options(self.jpeg, options))
        for exposure in ('nan', 'inf', '-2.01', '3.01', 'word'):
            with self.assertRaises(HTTPException):
                main._opts(dict(form, raw_exposure_ev=exposure))
        with self.assertRaises(HTTPException):
            main._opts(dict(form, raw_wb='invented'))

    def test_jpeg_upload_result_is_unchanged_when_raw_fields_are_submitted(self):
        response = self.client.post('/admin/new', files={'photo': ('photo.jpg', self.jpeg, 'image/jpeg')},
                                    data=dict(opts='1', raw_wb='auto', raw_exposure_ev='1.95',
                                              raw_tone='photographic'), follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        pid = response.headers['location'].rsplit('/', 1)[-1]
        self.assertNotIn('raw_settings', json.loads(db.get(pid)['options']))
        self.assertEqual(main._photo_path(pid).read_bytes(), self.result.jpeg)

    def test_reprocess_preserves_settings_and_accepts_explicit_changes(self):
        pid = self.store()
        with patch.object(P, 'process', return_value=self.result) as process:
            response = self.client.post(f'/admin/p/{pid}/reprocess', data={'opts': '1'}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(process.call_args.kwargs['raw_settings'], RAW_SETTINGS)
            changed = self.client.post(f'/admin/p/{pid}/reprocess', data=dict(opts='1', raw_wb='camera',
                                        raw_exposure_ev='0.5', raw_tone='neutral'), follow_redirects=False)
        self.assertEqual(changed.status_code, 303)
        self.assertEqual(json.loads(db.get(pid)['options'])['raw_settings'],
                         dict(wb='camera', exposure_ev=.5, tone='neutral'))
        self.assertEqual((config.PHOTO_DIR / f'{pid}_source').read_bytes(), self.raw)

    def test_source_previews_and_restore_use_the_saved_development(self):
        pid = self.store()
        rgb = P.load_image(self.jpeg)
        with patch.object(P, 'load_image', return_value=rgb) as load:
            for route in ('original.jpg', 'crop-source.jpg'):
                self.assertEqual(self.client.get(f'/admin/p/{pid}/{route}').status_code, 200)
                self.assertEqual(load.call_args.kwargs['raw_settings'], RAW_SETTINGS)
        with patch.object(P, 'load_image', side_effect=R.Unavailable('Install the local RAW decoder')):
            response = self.client.get(f'/admin/p/{pid}/original.jpg')
        self.assertEqual(response.status_code, 409)
        self.assertIn('RAW decoder', response.text)
        with patch.object(P, 'process', return_value=self.result) as process:
            response = self.client.post(f'/admin/p/{pid}/restore-original', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(process.call_args.kwargs['raw_settings'], RAW_SETTINGS)

    def test_native_quality_source_uses_the_saved_development(self):
        report = dict(version=R.VERSION, rawpy=R.RAWPY_VERSION, libraw=[0, 22, 1], settings=RAW_SETTINGS)
        self.result.measurements['raw_development'] = report
        pid = self.store()
        with patch.object(config, 'OFIQ_ENABLED', True), patch.object(main.ofiq, 'source_png', return_value=b'base') as source, \
                patch.object(main.ofiq, 'assess', return_value={}) as assess, \
                patch.object(P, 'save_photo', return_value=self.result.jpeg):
            response = self.client.post(f'/admin/p/{pid}/ofiq', data={'review_revision': db.get(pid)['revision']},
                                        follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        source.assert_called_once_with(self.raw, raw_settings=RAW_SETTINGS, expected_development=report)
        self.assertEqual(assess.call_args.args[0]['original'], b'base')
        self.assertEqual(json.loads(db.get(pid)['measurements'])['ofiq']['source_development'], report)

    def test_unavailable_ofiq_decoder_retains_saved_evidence_and_releases_edit_lock(self):
        self.result.measurements['raw_development'] = dict(version=R.VERSION, settings=RAW_SETTINGS)
        pid = self.store()
        before = db.get(pid)
        with patch.object(config, 'OFIQ_ENABLED', True), \
                patch.object(main.ofiq, 'source_png', side_effect=ValueError('RAW decoder is unavailable')), \
                patch.object(main.ofiq, 'assess') as assess, \
                patch.object(P, 'save_photo', return_value=self.result.jpeg):
            response = self.client.post(f'/admin/p/{pid}/ofiq', data={'review_revision': before['revision']},
                                        follow_redirects=False)
        self.assertEqual(response.status_code, 409)
        self.assertIn('decoder', response.text)
        assess.assert_not_called()
        after = db.get(pid)
        self.assertEqual(after['measurements'], before['measurements'])
        self.assertEqual(after['revision'], before['revision'])
        self.assertIsNone(after['edit_token'])
        self.assertEqual((config.PHOTO_DIR / f'{pid}_source').read_bytes(), self.raw)

    def test_legacy_raw_quality_requires_recorded_development_before_assessing(self):
        pid = self.store()
        before = db.get(pid)
        with patch.object(config, 'OFIQ_ENABLED', True), patch.object(main.ofiq, 'source_png') as source:
            response = self.client.post(f'/admin/p/{pid}/ofiq', data={'review_revision':before['revision']})
        self.assertEqual(response.status_code, 409)
        self.assertIn('previous development was not recorded', response.text)
        source.assert_not_called()
        self.assertEqual(db.get(pid)['measurements'], before['measurements'])
        self.assertIsNone(db.get(pid)['edit_token'])

    def test_optional_ai_receives_declared_raw_pixels_and_restore_keeps_its_settings(self):
        pid = self.store()
        rgb = P.load_image(self.jpeg)
        prepared = main.ai_prepare.PreparedImage(self.jpeg, 'mock-only', 'mock-request')
        with patch.object(config, 'OPENAI_API_KEY', 'mock-only'), \
                patch.object(P, 'process', return_value=self.result), \
                patch.object(P, 'load_image', return_value=rgb) as load, \
                patch.object(main.ai_prepare, 'prepare', return_value=prepared) as prepare:
            response = self.client.post(f'/admin/p/{pid}/ai/prepare',
                                       data={'ai_consent': 'on', 'lighting': 'on', 'colour': 'on'})
        self.assertEqual(response.status_code, 200)
        load.assert_called_once_with(self.raw, raw_settings=RAW_SETTINGS)
        self.assertTrue(prepare.call_args.args[0].startswith(b'\x89PNG'))
        state = json.loads(db.get(pid)['ai_state'])
        self.assertNotIn('raw_settings', state['options'])
        self.assertEqual(state['original_raw_settings'], RAW_SETTINGS)
        with patch.object(P, 'process', return_value=self.result):
            response = self.client.post(f'/admin/p/{pid}/ai/accept', data={
                'review_likeness': 'on', 'candidate_id': state['candidate_id']}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(json.loads(db.get(pid)['options'])['ai']['original_raw_settings'], RAW_SETTINGS)
        with patch.object(P, 'process', return_value=self.result) as process:
            response = self.client.post(f'/admin/p/{pid}/restore-original', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(process.call_args.kwargs['raw_settings'], RAW_SETTINGS)
        self.assertEqual((config.PHOTO_DIR / f'{pid}_source').read_bytes(), self.raw)

    def test_raw_download_is_private_byte_exact_and_never_uses_pillow(self):
        pid = self.store()
        url = f'/admin/p/{pid}/camera-original'
        self.assertEqual(TestClient(main.app).get(url).status_code, 401)
        with patch.object(P.Image, 'open', side_effect=AssertionError('CR2 is not a JPEG')):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.raw)
        self.assertIn('.cr2"', response.headers['content-disposition'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        with db.conn() as connection:
            connection.execute('UPDATE photos SET expires=0 WHERE id=?', (pid,))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_unsupported_cr2_envelope_is_retained_and_downloaded_without_pillow(self):
        pid = self.store()
        unsupported = self.raw[:10] + b'\x03' + self.raw[11:]
        (config.PHOTO_DIR / f'{pid}_source').write_bytes(unsupported)
        self.assertFalse(R.is_raw_signature(unsupported))
        self.assertTrue(main._retained_raw_source(pid))
        with patch.object(P.Image, 'open', side_effect=AssertionError('RAW container must not become a TIFF preview')):
            response = self.client.get(f'/admin/p/{pid}/camera-original')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, unsupported)
        self.assertIn('.cr2"', response.headers['content-disposition'])

    def test_issuance_retains_verified_raw_even_without_old_settings_metadata(self):
        pid = self.store(options={'auto_adjust': False}, country='united-kingdom-online-renewal')
        with patch.object(P, 'code_photo', return_value=self.result.jpeg), \
                patch.object(P, 'check_code_photo', return_value=self.result):
            response = self.client.post(f'/admin/p/{pid}/issue', data={
                'review_revision': db.get(pid)['revision'], 'review_likeness': 'on',
                'review_visibility': 'on', 'customer_permission': 'on'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual((config.PHOTO_DIR / f'{pid}_source').read_bytes(), self.raw)

    def test_raw_controls_are_separate_from_the_three_lighting_choices(self):
        fresh = self.client.get('/admin/new').text
        self.assertIn('accept="image/*,.cr2"', fresh)
        self.assertIn('id="raw-controls" hidden', fresh)
        pid = self.store()
        loaded = self.client.get(f'/admin/p/{pid}').text
        self.assertIn('id="raw-controls" >', loaded)
        self.assertIn('selected RAW development', loaded)
        self.assertIn('value="1.95"', loaded)
        for level in ('natural', 'balanced', 'recovery'):
            self.assertIn(f'data-enhance-preset="{level}"', loaded)


if __name__ == '__main__':
    unittest.main()
