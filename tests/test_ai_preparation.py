"""API contract, original preservation, review gates, exceptions and immutable codes.

No real OpenAI requests or customer photos are used.
Run: python3 tests/test_ai_preparation.py
"""
import base64
import hashlib
from html.parser import HTMLParser
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="tuttocode-ai-tests-"),
                  ADMIN_PASSWORD="test-only", HMPO_KEY_URL="", OPENAI_API_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
from starlette.testclient import TestClient
from app import ai_prepare, config, db, main, processing as P
from synthetic import Fake, make_face
logging.getLogger("httpx").setLevel(logging.WARNING)

REVIEW = {"review_likeness": "on", "review_visibility": "on", "customer_permission": "on"}


class PhotoForm(HTMLParser):
    """Successful default fields of the rendered studio form, excluding its file."""
    def __init__(self, html):
        super().__init__()
        self.fields = {}
        self.active = False
        self.select = None
        self.option = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.active = attrs.get('id') == 'photo-form'
        if not self.active:
            return
        if tag == 'input' and attrs.get('name') and 'disabled' not in attrs:
            kind = attrs.get('type', 'text')
            if kind in ('file', 'button', 'submit') or (kind in ('checkbox', 'radio') and 'checked' not in attrs):
                return
            self.fields[attrs['name']] = attrs.get('value', 'on' if kind in ('checkbox', 'radio') else '')
        if tag == 'select' and attrs.get('name') and 'disabled' not in attrs:
            self.select = (attrs['name'], [])
        if tag == 'option' and self.select:
            self.option = {'attrs': attrs, 'text': ''}

    def handle_data(self, data):
        if self.active and self.option is not None:
            self.option['text'] += data

    def handle_endtag(self, tag):
        if tag == 'option' and self.option is not None:
            self.select[1].append(self.option)
            self.option = None
        if tag == 'select' and self.select:
            name, options = self.select
            selected = next((o for o in options if 'selected' in o['attrs']), options[0])
            self.fields[name] = selected['attrs'].get('value', selected['text'].strip())
            self.select = None
        if tag == 'form':
            self.active = False


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.source, _ = make_face()

    def response(self, image):
        payload = json.dumps({"data": [{"b64_json": base64.b64encode(image).decode()}]}).encode()
        class Reply(io.BytesIO):
            headers = {"x-request-id": "req_test"}
        return Reply(payload)

    def test_current_image_edit_request_and_metadata(self):
        with patch.object(config, "OPENAI_API_KEY", "secret-not-for-browser"), patch.object(
            ai_prepare.urllib.request, "urlopen", return_value=self.response(self.source)) as call:
            result = ai_prepare.prepare(self.source)
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/images/edits")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "gpt-image-2")
        self.assertNotIn("input_fidelity", payload)
        self.assertEqual(payload["output_format"], "png")
        self.assertIn("Lightly clean skin surface noise", payload["prompt"])
        self.assertIn("gentle, natural sharpening only to existing visible detail", payload["prompt"])
        self.assertIn("facial biometrics", payload["prompt"])
        self.assertIn("Preserve every mole, freckle, scar, birthmark", payload["prompt"])
        self.assertIn("Reduce excessive specular shine and hotspots", payload["prompt"])
        self.assertIn("Correct overall exposure", payload["prompt"])
        self.assertIn("gently balance uneven facial illumination", payload["prompt"])
        self.assertIn("do not lighten or recolour their complexion", payload["prompt"])
        self.assertIn("do not darken clipped patches", payload["prompt"])
        self.assertIn("Do not crop, rotate, replace the background", payload["prompt"])
        self.assertNotIn("No beauty retouching, skin smoothing, blemish removal", payload["prompt"])
        self.assertNotIn("secret-not-for-browser", request.data.decode())
        self.assertEqual(result.request_id, "req_test")
        self.assertEqual(result.prompt_version, "portrait-cleanup-v2")
        self.assertEqual(result.image, self.source)
        normalized = Image.open(io.BytesIO(base64.b64decode(payload["images"][0]["image_url"].split(",")[1])))
        self.assertLessEqual(max(normalized.size), 2048)
        self.assertFalse(normalized.getexif())

    def test_legacy_high_fidelity_request(self):
        with patch.object(config, "OPENAI_API_KEY", "secret"), patch.object(config, "OPENAI_IMAGE_MODEL", "gpt-image-1.5"), patch.object(
            ai_prepare.urllib.request, "urlopen", return_value=self.response(self.source)) as call:
            ai_prepare.prepare(self.source, lighting=True, colour=False)
        payload = json.loads(call.call_args.args[0].data)
        self.assertEqual(payload["input_fidelity"], "high")
        self.assertEqual(payload["size"], "auto")

    def test_request_sizes_follow_api_limits(self):
        for size in ((2048, 1801), (3000, 1000), (1000, 3000)):
            image = io.BytesIO()
            Image.new("RGB", size, "grey").save(image, "JPEG")
            data = image.getvalue()
            with patch.object(config, "OPENAI_API_KEY", "test"), patch.object(ai_prepare.urllib.request, "urlopen", return_value=self.response(data)) as call:
                ai_prepare.prepare(data)
            width, height = map(int, json.loads(call.call_args.args[0].data)["size"].split("x"))
            self.assertEqual(width % 16, 0)
            self.assertEqual(height % 16, 0)
            self.assertLessEqual(width * height, 3_686_400)
            self.assertLessEqual(max(width / height, height / width), 3)

    def test_no_key_no_remote_request(self):
        with patch.object(ai_prepare.urllib.request, "urlopen") as call:
            with self.assertRaises(ai_prepare.PreparationError):
                ai_prepare.prepare(self.source)
            call.assert_not_called()

    def test_timeout_is_reported_without_retries(self):
        with patch.object(config, "OPENAI_API_KEY", "secret"), patch.object(ai_prepare.urllib.request, "urlopen", side_effect=TimeoutError) as call:
            with self.assertRaises(ai_prepare.PreparationError):
                ai_prepare.prepare(self.source)
        self.assertEqual(call.call_count, 1)

    def test_errors_do_not_disclose_provider_payloads_or_key(self):
        exc = urllib.error.HTTPError(ai_prepare.ENDPOINT, 401, "secret-not-for-browser", {}, io.BytesIO(b"private provider payload"))
        with patch.object(config, "OPENAI_API_KEY", "secret-not-for-browser"), patch.object(ai_prepare.urllib.request, "urlopen", side_effect=exc):
            with self.assertRaises(ai_prepare.PreparationError) as caught:
                ai_prepare.prepare(self.source)
        self.assertNotIn("secret-not-for-browser", str(caught.exception))
        self.assertNotIn("payload", str(caught.exception))

    def test_distorted_or_unreadable_output_is_rejected(self):
        blob = io.BytesIO()
        Image.new("RGB", (1024, 1024)).save(blob, "PNG")
        for output in (blob.getvalue(), b"not an image"):
            with patch.object(config, "OPENAI_API_KEY", "secret"), patch.object(ai_prepare.urllib.request, "urlopen", return_value=self.response(output)):
                with self.assertRaises(ai_prepare.PreparationError):
                    ai_prepare.prepare(self.source)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source, analysis = make_face()
        P._analyzer = Fake(analysis)
        self.client = TestClient(main.app, headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-only").decode()})
        db.init()

    def upload(self, **fields):
        response = self.client.post("/admin/new", data={"opts": "1", **fields}, files={"photo": ("camera.jpg", self.source, "image/jpeg")}, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        return response.headers["location"].rsplit("/", 1)[1]

    def prepare(self, pid):
        with patch.object(config, "OPENAI_API_KEY", "test-secret"), patch.object(ai_prepare, "prepare", return_value=ai_prepare.PreparedImage(self.source, "mock-image-model", "req_test")):
            response = self.client.post(f"/admin/p/{pid}/ai/prepare", data={"lighting": "on", "colour": "on", "ai_consent": "on"})
        self.assertEqual(response.status_code, 200, response.text)

    def issue(self, pid, **fields):
        return self.client.post(f"/admin/p/{pid}/issue", data={**REVIEW, "review_revision": str(db.get(pid)["revision"]), **fields}, follow_redirects=False)

    def accept(self, pid):
        candidate = json.loads(db.get(pid)["ai_state"])["candidate_id"]
        return self.client.post(f"/admin/p/{pid}/ai/accept", data={"review_likeness": "on", "candidate_id": candidate}, follow_redirects=False)

    def test_complete_rendered_studio_form_uploads_and_crop_controls_change_photo(self):
        fields = PhotoForm(self.client.get('/admin/new').text).fields
        self.assertLessEqual(len(fields),30,'Staff profiles replace the expanded technical form')
        self.assertEqual(fields['adaptive_profile'],'balanced')
        # Continue exercising the original multipart parser regression even
        # though the actual staff form is now smaller.
        fields.update({f'compatibility_field_{i}':'0' for i in range(35)})
        with patch.object(ai_prepare, 'prepare', side_effect=AssertionError('OpenAI was not selected')):
            response = self.client.post('/admin/new', data=fields,
                files={'photo': ('camera.jpg', self.source, 'image/jpeg')}, follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
            path = response.headers['location']
            before = self.client.get(path + '/full.jpg').content
            fields.update(zoom='0.84', x='-17', y='9', angle='-3')
            response = self.client.post(path + '/reprocess', data=fields, follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
        row = db.get(path.rsplit('/', 1)[1])
        self.assertEqual(json.loads(row['options'])['crop'],
                         dict(zoom=.84, x=-17., y=9., rotation=0, angle=-3.))
        after = self.client.get(path + '/full.jpg').content
        self.assertNotEqual(hashlib.sha256(before).hexdigest(), hashlib.sha256(after).hexdigest())
        Image.open(io.BytesIO(after)).verify()

    def test_upload_field_count_remains_bounded(self):
        with patch.object(P, 'process', side_effect=AssertionError('Oversized form must not process')):
            response = self.client.post('/admin/new', data={f'field_{i}': '0' for i in range(101)},
                files={'photo': ('camera.jpg', self.source, 'image/jpeg')}, follow_redirects=False)
        self.assertEqual(response.status_code, 400)

    def test_simple_studio_uk_online_uses_its_own_crop_and_export(self):
        fields = PhotoForm(self.client.get('/admin/new').text).fields
        profile = main.photomatic.country('united-kingdom-online-renewal')
        fields.update(country_id=profile['id'],
                      print_template_id=main.photomatic.default_print(profile)['id'])
        response = self.client.post('/admin/new', data=fields,
            files={'photo': ('camera.jpg', self.source, 'image/jpeg')}, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        path = response.headers['location']
        row = db.get(path.rsplit('/', 1)[-1])
        measures = json.loads(row['measurements'])
        self.assertEqual(measures['output_size'], [1500, 2100])
        self.assertAlmostEqual(measures['eye_height_percent'], 32, places=3)
        exported = self.client.get(path + '/save.jpg')
        self.assertEqual(Image.open(io.BytesIO(exported.content)).size, (800, 1120))

    def test_failed_crop_keeps_camera_original_visible_for_adjustment(self):
        pid = self.upload(zoom='.5')
        self.assertFalse(main._photo_path(pid).exists())
        page = self.client.get(f'/admin/p/{pid}').text
        self.assertIn(f'src="/admin/p/{pid}/original.jpg"', page)
        self.assertIn('Camera original · adjust the crop', page)
        self.assertIn('id="crop-controls" open', page)
        self.assertEqual(self.client.get(f'/admin/p/{pid}/original.jpg').status_code, 200)

    def test_upload_automatically_prepares_when_selected(self):
        with patch.object(config, "OPENAI_API_KEY", "test-secret"), patch.object(ai_prepare, "prepare", return_value=ai_prepare.PreparedImage(self.source, "mock-image-model", "req_test")) as call:
            response = self.client.post("/admin/new", data={"opts": "1", "use_ai": "on"}, files={"photo": ("camera.jpg", self.source)}, follow_redirects=False)
            self.assertEqual(response.status_code, 400)
            call.assert_not_called()
            pid = self.upload(use_ai="on", ai_consent="on")
        call.assert_called_once()
        self.assertEqual(json.loads(db.get(pid)["ai_state"])["status"], "ready")
        self.assertIsNone(db.get(pid)["code"])
        page = self.client.get(f"/admin/p/{pid}")
        self.assertIn("Detailed AI preview measurements", page.text)

    def test_metrics_are_persisted_as_actual_measurements(self):
        pid = self.upload()
        row = db.get(pid)
        measured = json.loads(row["measurements"])
        self.assertEqual(measured["input_size"], list(Image.open(io.BytesIO(self.source)).size))
        self.assertEqual(measured["output_size"], [1050, 1350])
        self.assertAlmostEqual(measured["eye_height_percent"], 48, places=3)
        distance = ((measured["eye2"][0] - measured["eye1"][0])**2 + (measured["eye2"][1] - measured["eye1"][1])**2)**.5
        self.assertAlmostEqual(measured["output_eye_distance"], distance, places=1)
        self.assertGreater(measured["sharpness"], 0)
        self.assertNotIn("measurement_confidence", measured)

    def test_local_refresh_preserves_paid_source_and_requires_current_preview(self):
        pid=self.upload();self.prepare(pid)
        row=db.get(pid);state=json.loads(row['ai_state'])
        source_path=config.PHOTO_DIR/f'{pid}_ai_source';source=source_path.read_bytes()
        form={'candidate_id':state['candidate_id'],'review_revision':str(row['revision'])}
        with patch.object(ai_prepare,'prepare',side_effect=AssertionError('No paid call')):
            response=self.client.post(f'/admin/p/{pid}/ai/recheck',data=form)
        self.assertEqual(response.status_code,200,response.text)
        refreshed=json.loads(db.get(pid)['ai_state'])
        self.assertFalse(response.json()['openai_called'])
        self.assertEqual(source_path.read_bytes(),source)
        self.assertEqual(refreshed['request_id'],state['request_id'])
        self.assertNotEqual(refreshed['candidate_id'],state['candidate_id'])
        self.assertEqual(refreshed['revision'],row['revision']+1)
        self.assertEqual(self.client.post(f'/admin/p/{pid}/ai/recheck',data=form).status_code,409)
        self.assertIsNone(db.get(pid)['code'])

    def test_ai_preview_preserves_selected_background_tool(self):
        pid=self.upload(replace_bg='on',background_engine='mediapipe')
        self.prepare(pid)
        state=json.loads(db.get(pid)['ai_state'])
        self.assertTrue(state['options']['replace_bg'])
        self.assertEqual(state['measurements']['background_removal']['engine'],'mediapipe')

    def test_local_refresh_rejects_changed_paid_source_and_is_private(self):
        pid=self.upload();self.prepare(pid)
        row=db.get(pid);state=json.loads(row['ai_state'])
        form={'candidate_id':state['candidate_id'],'review_revision':str(row['revision'])}
        with TestClient(main.app) as public:
            self.assertEqual(public.post(f'/admin/p/{pid}/ai/recheck',data=form).status_code,401)
        (config.PHOTO_DIR/f'{pid}_ai_source').write_bytes(b'changed')
        self.assertEqual(self.client.post(f'/admin/p/{pid}/ai/recheck',data=form).status_code,409)
        self.assertEqual(json.loads(db.get(pid)['ai_state'])['candidate_id'],state['candidate_id'])

    def test_invalid_fine_rotation_rejected(self):
        pid = self.upload()
        for angle in ("nan", "16", "-16", "invalid"):
            response = self.client.post(f"/admin/p/{pid}/reprocess", data={"angle": angle})
            self.assertEqual(response.status_code, 400)

    def test_ai_controls_and_original_are_staff_only(self):
        pid = self.upload()
        with TestClient(main.app) as public:
            for path in ("original.jpg", "ai-preview.jpg", "crop-source.jpg"):
                self.assertEqual(public.get(f"/admin/p/{pid}/{path}").status_code, 401)
            self.assertEqual(public.post(f"/admin/p/{pid}/ai/prepare").status_code, 401)

    def test_crop_preview_source_uses_working_image_without_models_or_api(self):
        pid=self.upload()
        data=io.BytesIO();Image.new('RGB',(800,1000),'blue').save(data,'PNG')
        (config.PHOTO_DIR/f'{pid}_working_source').write_bytes(data.getvalue())
        with patch.object(P,'get_analyzer',side_effect=AssertionError('No analysis needed')),patch.object(ai_prepare,'prepare',side_effect=AssertionError('No API needed')):
            response=self.client.get(f'/admin/p/{pid}/crop-source.jpg')
        self.assertEqual(response.status_code,200)
        image=Image.open(io.BytesIO(response.content));self.assertEqual(image.size,(800,1000))
        self.assertGreater(image.getpixel((100,100))[2],240)

    def test_prepare_review_recheck_issue_and_signed_fetch(self):
        pid = self.upload()
        original_master = main._photo_path(pid).read_bytes()
        self.prepare(pid)
        self.assertEqual(json.loads(db.get(pid)["ai_state"])["prompt_version"], "portrait-cleanup-v2")
        self.assertEqual(main._photo_path(pid).read_bytes(), original_master)
        self.assertEqual((config.PHOTO_DIR / f"{pid}_source").read_bytes(), self.source)
        self.assertEqual(self.issue(pid).status_code, 409)
        self.assertEqual(self.client.post(f"/admin/p/{pid}/ai/accept").status_code, 400)
        accepted = self.accept(pid)
        self.assertEqual(accepted.status_code, 303, accepted.text)
        self.assertEqual(json.loads(db.get(pid)["options"])["ai"]["model"], "mock-image-model")
        self.assertEqual(json.loads(db.get(pid)["options"])["ai"]["prompt_version"], "portrait-cleanup-v2")
        self.assertFalse((config.PHOTO_DIR / f"{pid}_ai.jpg").exists())
        page = self.client.get(f"/admin/p/{pid}")
        self.assertIn("Detailed measurements", page.text)
        self.assertIn("Not tested", page.text)
        self.assertNotIn("test-secret", page.text)
        issued_response = self.issue(pid)
        self.assertEqual(issued_response.status_code, 303, issued_response.text)
        row = db.get(pid)
        issued = (config.PHOTO_DIR / f"{pid}_code.jpg").read_bytes()
        self.assertEqual(json.loads(row["issue_review"])["photo_sha256"], hashlib.sha256(issued).hexdigest())
        self.assertTrue((config.PHOTO_DIR / f"{pid}_source").exists())
        with patch.object(main.hmpo_auth, "verify", return_value=(True, "test")):
            delivered = self.client.get(f"/{row['code']}", headers={"host": config.SHORT_DOMAIN})
        self.assertEqual(delivered.content, issued)
        self.assertEqual(self.client.post(f"/admin/p/{pid}/ai/prepare").status_code, 503)
        with patch.object(config, "OPENAI_API_KEY", "test"):
            self.assertEqual(self.client.post(f"/admin/p/{pid}/ai/prepare", data={"ai_consent": "on"}).status_code, 409)
        self.assertEqual(self.client.post(f"/admin/p/{pid}/reprocess").status_code, 409)
        self.assertEqual(self.issue(pid).status_code, 303)  # Idempotent, no new code.
        self.assertEqual(db.get(pid)["code"], row["code"])

    def test_permissions_and_remote_failure_keep_current_photo(self):
        pid = self.upload()
        before = main._photo_path(pid).read_bytes()
        with patch.object(config, "OPENAI_API_KEY", "test"), patch.object(ai_prepare, "prepare", side_effect=RuntimeError("private secret provider payload")) as call:
            self.assertEqual(self.client.post(f"/admin/p/{pid}/ai/prepare", data={"lighting": "on"}).status_code, 400)
            call.assert_not_called()
            response = self.client.post(f"/admin/p/{pid}/ai/prepare", data={"ai_consent": "on", "lighting": "on"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("private secret", response.text)
        self.assertEqual(main._photo_path(pid).read_bytes(), before)
        self.assertIsNone(db.get(pid)["edit_token"])
        self.assertEqual(self.client.post(f"/admin/p/{pid}/issue", data={"review_revision": str(db.get(pid)["revision"])}).status_code, 400)

    def test_photo_lock_blocks_issue_reprocess_and_deletion(self):
        pid = self.upload()
        token = db.claim_edit(pid)
        try:
            for action in ("issue", "reprocess", "reject"):
                self.assertEqual(self.client.post(f"/admin/p/{pid}/{action}", data=REVIEW).status_code, 409)
        finally:
            db.release_edit(pid, token)

    def test_pending_preview_is_discarded_by_crop_change(self):
        pid = self.upload()
        self.prepare(pid)
        response = self.client.post(f"/admin/p/{pid}/reprocess", data={"opts": "1", "x": "1"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get(f"/admin/p/{pid}/ai-preview.jpg").status_code, 404)
        self.assertEqual(self.client.post(f"/admin/p/{pid}/ai/accept", data={"review_likeness": "on"}).status_code, 409)

    def test_discard_and_restore_original(self):
        pid = self.upload()
        before = main._photo_path(pid).read_bytes()
        self.prepare(pid)
        self.client.post(f"/admin/p/{pid}/ai/discard", follow_redirects=False)
        self.assertEqual(main._photo_path(pid).read_bytes(), before)
        self.prepare(pid)
        self.accept(pid)
        self.client.post(f"/admin/p/{pid}/restore-original", follow_redirects=False)
        self.assertNotIn("ai", json.loads(db.get(pid)["options"]))
        self.assertEqual(main._photo_path(pid).read_bytes(), before)

    def set_failure(self, pid, key):
        with db.conn() as c:
            c.execute("UPDATE photos SET ok=0, checks=? WHERE id=?", (json.dumps([{"key": key, "label": key, "status": "fail", "detail": "test failure"}]), pid))

    def test_named_allowance_without_staff_override_needs_specific_evidence(self):
        pid = self.upload()
        self.set_failure(pid, "eyes")
        self.assertEqual(self.issue(pid, override="on").status_code, 400)
        exception = dict(exception_category="health", exception_reason="Document allowance for a recorded eye condition", exception_checks="eyes", exception_confirmed="on")
        self.assertEqual(self.issue(pid, **{**exception, "exception_reason": "short"}).status_code, 400)
        self.assertEqual(self.issue(pid, **{**exception, "exception_category": "child"}).status_code, 400)
        self.assertEqual(self.issue(pid, **{**exception, "exception_checks": "expression"}).status_code, 400)
        response = self.issue(pid, **exception)
        self.assertEqual(response.status_code, 303, response.text)
        record = json.loads(db.get(pid)["issue_review"])
        self.assertEqual(record["decision"], "approved_with_exception")
        self.assertEqual(record["exception"]["checks"], ["eyes"])
        self.assertFalse(db.get(pid)["ok"])  # Never relabel the failed metric.

    def test_quality_and_export_failures_need_explicit_staff_override(self):
        for key in ("resolution", "sharp", "exposure", "background", "framing", "filesize"):
            pid = self.upload()
            self.set_failure(pid, key)
            response = self.issue(pid, exception_category="other", exception_reason="Some attempted general waiver", exception_checks=key, exception_confirmed="on")
            self.assertEqual(response.status_code, 400, key)
            self.assertIsNone(db.get(pid)["code"])
        pid = self.upload(country_id="uk-online")
        # This imported template has a digital aspect different from its master.
        response = self.issue(pid)
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(db.get(pid)["code"])

    def test_online_renewal_code_has_required_digital_dimensions(self):
        pid = self.upload(country_id="united-kingdom-online-renewal")
        result = self.issue(pid)
        self.assertEqual(result.status_code, 303, result.text)
        with Image.open(config.PHOTO_DIR / f"{pid}_code.jpg") as image:
            self.assertEqual(image.size, (800, 1120))

    def test_failure_on_final_encoded_jpeg_blocks_issue_and_is_visible(self):
        pid = self.upload()
        failed = P.Result(False, [P.Check("sharp", "In focus", "fail", "Blurred after export")], measurements={"sharpness": 12.5})
        with patch.object(P, "check_code_photo", return_value=failed):
            result = self.issue(pid)
        self.assertEqual(result.status_code, 400)
        self.assertIsNone(db.get(pid)["code"])
        page = self.client.get(f"/admin/p/{pid}")
        self.assertIn("Final code JPEG measurements", page.text)
        self.assertIn("12.5", page.text)
        self.assertFalse((config.PHOTO_DIR / f"{pid}_code.jpg").exists())

    def test_new_codes_never_fall_back_to_master_when_issued_file_is_missing_or_changed(self):
        pid = self.upload()
        self.assertEqual(self.issue(pid).status_code, 303)
        path = config.PHOTO_DIR / f"{pid}_code.jpg"
        with patch.object(main.hmpo_auth, "verify", return_value=(True, "test")):
            path.write_bytes(b"changed JPEG bytes")
            self.assertEqual(self.client.get(f"/{db.get(pid)['code']}", headers={"host": config.SHORT_DOMAIN}).status_code, 404)
            path.unlink()
            self.assertTrue(main._photo_path(pid).exists())
            self.assertEqual(self.client.get(f"/{db.get(pid)['code']}", headers={"host": config.SHORT_DOMAIN}).status_code, 404)

    def test_child_allowance_is_kept_in_issue_record(self):
        pid = self.upload(age_group="baby")
        result = self.issue(pid)
        self.assertEqual(result.status_code, 303, result.text)
        record = json.loads(db.get(pid)["issue_review"])
        self.assertEqual(record["age_group"], "baby")
        self.assertIn("eyes", record["age_allowances"])
        self.assertEqual(record["decision"], "approved_with_age_allowance")

    def test_stale_staff_review_or_replaced_ai_preview_cannot_be_used(self):
        pid = self.upload()
        old_revision = db.get(pid)["revision"]
        self.client.post(f"/admin/p/{pid}/reprocess", data={"opts": "1", "x": "1"}, follow_redirects=False)
        self.assertEqual(self.issue(pid, review_revision=str(old_revision)).status_code, 409)
        self.prepare(pid)
        first_candidate = json.loads(db.get(pid)["ai_state"])["candidate_id"]
        self.prepare(pid)
        self.assertEqual(self.client.post(f"/admin/p/{pid}/ai/accept", data={"review_likeness": "on", "candidate_id": first_candidate}).status_code, 409)

    def test_irish_workflow_export_without_our_code(self):
        pid = self.upload(country_id="ireland-passport-online")
        self.assertEqual(self.issue(pid).status_code, 503)
        page = self.client.get(f"/admin/p/{pid}")
        self.assertIn("external provider", page.text)
        exported = self.client.get(f"/admin/p/{pid}/save.jpg")
        self.assertEqual(Image.open(io.BytesIO(exported.content)).size, (715, 951))
        self.assertIsNone(db.get(pid)["code"])

    def test_reject_deletes_all_ai_artifacts(self):
        pid = self.upload()
        self.prepare(pid)
        self.client.post(f"/admin/p/{pid}/reject", follow_redirects=False)
        self.assertIsNone(db.get(pid))
        self.assertFalse(any(config.PHOTO_DIR.glob(f"{pid}*")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
