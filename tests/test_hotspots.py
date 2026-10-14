"""Controlled highlight fixtures and staff-only snapshot/approval invariants."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="tuttocode-hotspots-"),
                  ADMIN_PASSWORD="test-only", OPENAI_API_KEY="", HMPO_KEY_URL="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from PIL import Image
from starlette.testclient import TestClient
from app import config, db, hotspots, main, processing as P


def fixture(colour=(165, 130, 110)):
    rgb = np.full((320, 320, 3), colour, np.uint8)
    points = np.tile([160., 160.], (478, 1))
    angles = np.linspace(-np.pi / 2, np.pi * 1.5, len(hotspots.FACE_OVAL), endpoint=False)
    points[hotspots.FACE_OVAL] = np.c_[160 + 90 * np.cos(angles), 160 + 125 * np.sin(angles)]
    points[P.FOREHEAD], points[P.CHIN] = [160, 35], [160, 285]
    points[P.FACE_L], points[P.FACE_R] = [70, 160], [250, 160]
    points[P.L_IRIS], points[P.R_IRIS], points[P.NOSE] = [125, 130], [195, 130], [160, 172]
    for indices, center, axes in [(P.LEFT_EYE_RING, (125, 130), (15, 6)),
                                  (P.RIGHT_EYE_RING, (195, 130), (15, 6)),
                                  (hotspots.LIPS, (160, 225), (25, 8))]:
        a = np.linspace(0, 2*np.pi, len(indices), endpoint=False)
        points[indices] = np.c_[center[0]+axes[0]*np.cos(a), center[1]+axes[1]*np.sin(a)]
    points[61], points[291] = [135, 225], [185, 225]
    return rgb, points


class MeasurementsTests(unittest.TestCase):
    def test_uniform_complexions_are_not_bright_patches(self):
        for colour in ((65, 45, 35), (165, 130, 110), (230, 210, 190)):
            rgb, points = fixture(colour)
            r = hotspots.measure(rgb, points)
            self.assertEqual(r["patch_count"], 0)
            self.assertEqual(r["near_clip_all_percent"], 0)

    def test_local_clipped_patch_is_localized_and_native_pixels_are_counted(self):
        rgb, points = fixture()
        rgb[85:95, 155:165] = 255
        r = hotspots.measure(rgb, points)
        forehead = next(region for region in r["regions"] if region["key"] == "forehead")
        self.assertGreater(forehead["near_clip_all_percent"], 0)
        self.assertEqual(r["patch_count"], 1)
        self.assertEqual(r["patches"][0]["pixels"], 100)
        self.assertEqual(r["patches"][0]["box"], [round(155/320, 6), round(85/320, 6), round(10/320, 6), round(10/320, 6)])

    def test_white_background_eye_whites_and_lips_are_excluded(self):
        rgb, points = fixture()
        rgb[:20] = 255
        cv2.ellipse(rgb, (125, 130), (10, 3), 0, 0, 360, (255,255,255), -1)
        cv2.ellipse(rgb, (195, 130), (10, 3), 0, 0, 360, (255,255,255), -1)
        cv2.ellipse(rgb, (160, 225), (18, 3), 0, 0, 360, (255,255,255), -1)
        r = hotspots.measure(rgb, points)
        self.assertEqual(r["patch_count"], 0)

    def test_one_channel_clipping_is_not_reported_as_all_channels(self):
        rgb, points = fixture()
        rgb[85:95,155:165] = (255,170,120)
        r = hotspots.measure(rgb, points)
        forehead = r["regions"][0]
        self.assertGreater(forehead["near_clip_any_percent"], 0)
        self.assertEqual(forehead["near_clip_all_percent"], 0)

    def test_image_side_labels_follow_a_mirrored_photo(self):
        rgb, points = fixture()
        rgb[168:178,110:120] = 255
        before = hotspots.measure(rgb, points)
        mirrored = points.copy(); mirrored[:,0] = 319 - mirrored[:,0]
        after = hotspots.measure(np.ascontiguousarray(rgb[:,::-1]), mirrored)
        by_key = lambda report:{r["key"]:r for r in report["regions"]}
        self.assertGreater(by_key(before)["image_left_cheek"]["near_clip_all_percent"], 0)
        self.assertEqual(by_key(before)["image_right_cheek"]["near_clip_all_percent"], 0)
        self.assertGreater(by_key(after)["image_right_cheek"]["near_clip_all_percent"], 0)
        self.assertEqual(by_key(after)["image_left_cheek"]["near_clip_all_percent"], 0)

    def test_bad_landmarks_and_masks_cannot_produce_measurements(self):
        rgb, points = fixture()
        for invalid in (points[:100], points * np.nan, np.zeros((478,2))):
            with self.assertRaises(ValueError): hotspots.measure(rgb, invalid)
        with self.assertRaises(ValueError): hotspots.measure(rgb, points, np.zeros((10,10)))

    def test_uniform_illumination_change_does_not_invent_recovered_detail(self):
        rgb, points = fixture()
        rgb[85:95,155:165] = 255
        before = hotspots.measure(rgb, points)
        after = hotspots.measure((rgb * .7).astype(np.uint8), points)
        self.assertGreater(before["near_clip_all_percent"], after["near_clip_all_percent"])
        self.assertEqual(after["status"], "diagnostic")
        self.assertNotIn("recovered_detail", after)
        self.assertNotIn("pass", after.values())


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.rgb, self.points = fixture()
        b = io.BytesIO(); Image.fromarray(self.rgb).save(b,"PNG"); self.data = b.getvalue()
        self.analyzer = type("Analyzer", (), {"analyze": lambda _, rgb: P.Analysis([P.FaceData(self.points, {})], None)})()
        self.client = TestClient(main.app, headers={"Authorization":"Basic "+base64.b64encode(b"admin:test-only").decode()})
        db.init()
        self.pid = db.new_id()
        result = P.Result(False, [P.Check("framing","Framing","fail")])
        db.create(self.pid, "shop", "adult", result)
        (config.PHOTO_DIR / (self.pid+"_source")).write_bytes(self.data)

    def request(self):
        with patch.object(P, "get_analyzer", return_value=self.analyzer):
            return self.client.get(f"/admin/p/{self.pid}/hotspots")

    def test_read_only_inspection_works_for_rejected_crop_and_is_staff_only(self):
        before = dict(db.get(self.pid)); response = self.request()
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["stages"][0]["status"], "diagnostic")
        self.assertFalse(report["calibrated"])
        self.assertEqual(report["approval"], "not_assessed")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(dict(db.get(self.pid)), before)
        with TestClient(main.app) as public:
            self.assertEqual(public.get(f"/admin/p/{self.pid}/hotspots").status_code, 401)

    def test_preview_is_an_exact_snapshot_not_a_mutable_image_url(self):
        r = self.request().json()["stages"][0]
        self.assertTrue(r["preview"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(r["image_size"], [320,320])
        self.assertEqual(len(r["image_sha256"]), 64)

    def test_original_current_and_candidate_are_distinct_stages(self):
        for suffix in (".jpg", "_ai_source"):
            (config.PHOTO_DIR / (self.pid+suffix)).write_bytes(self.data)
        with db.conn() as c:
            c.execute("UPDATE photos SET ai_state=? WHERE id=?",(json.dumps({"status":"ready","revision":0}),self.pid))
        self.assertEqual(len(self.request().json()["stages"]),3)

    def test_expiry_and_processing_are_not_inspected(self):
        token = db.claim_edit(self.pid)
        self.assertEqual(self.request().status_code,409)
        db.release_edit(self.pid,token)
        with db.conn() as c:c.execute("UPDATE photos SET expires=? WHERE id=?",(time.time()-1,self.pid))
        self.assertEqual(self.request().status_code,404)

    def test_revision_change_during_analysis_rejects_stale_report(self):
        def changing_analyzer(rgb):
            with db.conn() as c:c.execute("UPDATE photos SET revision=revision+1 WHERE id=?",(self.pid,))
            return P.Analysis([P.FaceData(self.points,{})],None)
        self.analyzer.analyze = changing_analyzer
        self.assertEqual(self.request().status_code,409)

    def test_missing_face_is_unavailable_not_green(self):
        self.analyzer.analyze = lambda rgb:P.Analysis([],None)
        r = self.request().json()["stages"][0]
        self.assertEqual(r["status"],"unavailable")
        self.assertEqual(r["approval"],"not_assessed")


if __name__ == "__main__":unittest.main()
