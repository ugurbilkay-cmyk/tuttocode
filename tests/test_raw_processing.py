"""RAW float precision, exact crop comparisons and optional-runtime failures.

Synthetic decoded masters exercise the real crop/lighting pipeline without
committing customer sensor files or requiring rawpy in the application runtime.
"""
import copy
from dataclasses import asdict
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import processing as P, raw_development as R, adaptive_quality as A, comparison, config, ofiq
from synthetic import Fake, make_face

RAW_BYTES = b"II*\x00\x10\x00\x00\x00CR\x02\x00\x00\x00\x00\x00synthetic-cr2-envelope"


class RawProcessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jpeg, cls.analysis = make_face(W=1600, H=2100, scale=.7)
        cls.rgb = P.load_image(cls.jpeg)
        # A sub-byte component unavailable from the preview makes a premature
        # sRGB8 round trip measurably different from the float crop.
        linear = A._linear(cls.rgb)
        ramp = .00013 * np.sin(np.arange(linear.shape[1], dtype=np.float32) * .7)[None, :, None]
        cls.linear = np.maximum(linear + ramp, 0).astype(np.float32)
        cls.preview = R.render(cls.linear)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        data_patch = patch.object(config, "DATA_DIR", Path(self.folder.name))
        data_patch.start(); self.addCleanup(data_patch.stop)
        self.settings = asdict(R.RawSettings())
        self.report = dict(version=R.VERSION, rawpy=R.RAWPY_VERSION, libraw=[0, 22, 1],
                           source_sha256=hashlib.sha256(RAW_BYTES).hexdigest(),
                           settings=self.settings.copy(), developed_size=[1600, 2100])
        self.options = dict(auto_adjust=False, fix_shadows=False, even_bg=False, replace_bg=False,
                            enhancement_options={"adaptive_profile": "off"})
        self.decoder = patch.object(R, "decode", side_effect=self.decoded)
        self.worker = self.decoder.start(); self.addCleanup(self.decoder.stop)
        off = patch.object(config, "OFIQ_ENABLED", False); off.start(); self.addCleanup(off.stop)

    def decoded(self, source, settings=None, **kwargs):
        self.assertEqual(Path(source).read_bytes(), RAW_BYTES)
        report = copy.deepcopy(self.report)
        if settings is not None:
            report["settings"] = asdict(settings) if isinstance(settings, R.RawSettings) else dict(settings)
        return R.DecodedSource(self.linear, self.preview, report)

    def process(self, **values):
        return P.process(RAW_BYTES, analyzer=Fake(self.analysis), **dict(self.options, **values))

    def test_raw_intercept_never_asks_pillow_for_embedded_jpeg(self):
        with patch.object(P.Image, "open", side_effect=AssertionError("Embedded JPEG is not a RAW decode")):
            rgb, master, report = P.load_source(RAW_BYTES, self.settings)
        np.testing.assert_array_equal(master, self.linear)
        np.testing.assert_array_equal(rgb, self.preview)
        self.assertEqual(report["settings"], self.settings)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_unsupported_canon_tiff_version_never_falls_back_to_embedded_jpeg(self):
        unsupported = RAW_BYTES[:10] + b"\x03\x00" + RAW_BYTES[12:]
        self.assertTrue(R.is_raw_container(unsupported))
        self.assertFalse(R.is_raw_signature(unsupported))
        with patch.object(P.Image, "open", side_effect=AssertionError("Unsupported RAW reached Pillow")):
            with self.assertRaises(R.InvalidRaw):
                P.load_source(unsupported)
        self.worker.assert_not_called()

    def test_tiff_input_is_rejected_instead_of_becoming_an_8bit_raw_preview(self):
        stream = io.BytesIO()
        Image.new("RGB", (64, 80), (120, 90, 70)).save(stream, "TIFF")
        with self.assertRaises(R.InvalidRaw) as caught:
            P.load_source(stream.getvalue())
        self.assertIn("TIFF", str(caught.exception))
        self.worker.assert_not_called()

    def test_jpeg_decode_stays_byte_identical_and_ignores_raw_settings(self):
        baseline = P.process(self.jpeg, analyzer=Fake(self.analysis), **self.options)
        current = P.process(self.jpeg, analyzer=Fake(self.analysis), raw_settings={"wb": "auto", "exposure_ev": 1.95,
                                                                                 "tone": "photographic"}, **self.options)
        self.worker.assert_not_called()
        self.assertEqual(baseline.jpeg, current.jpeg)
        self.assertEqual(baseline.before_jpeg, current.before_jpeg)
        self.assertNotIn("raw_development", current.measurements)

    def test_real_crop_uses_float_master_and_no_edit_comparison_is_exact(self):
        result = self.process()
        self.assertIsNotNone(result.jpeg, [c.__dict__ for c in result.checks])
        self.assertEqual(result.before_jpeg, result.jpeg)
        self.assertEqual(result.measurements["comparison"]["status"], "matched")
        report = result.measurements["raw_development"]
        x, y, width, height = result.measurements["crop_geometry"]["source_rect"]
        out_w, out_h = report["working_size"]
        matrix = np.array([[out_w / width, 0, -x * out_w / width],
                           [0, out_h / height, -y * out_h / height]], np.float32)
        expected = cv2.warpAffine(self.linear, matrix, (out_w, out_h), flags=cv2.INTER_AREA,
                                  borderMode=cv2.BORDER_REPLICATE)
        self.assertEqual(report["working_linear_sha256"], hashlib.sha256(expected.tobytes()).hexdigest())
        self.assertEqual(result.jpeg, P._encode_jpeg(R.render(expected)))
        quantized = cv2.warpAffine(self.preview, matrix, (out_w, out_h), flags=cv2.INTER_AREA,
                                   borderMode=cv2.BORDER_REPLICATE)
        self.assertGreater(np.count_nonzero(R.render(expected) != quantized), 500)
        self.assertNotEqual(result.jpeg, P._encode_jpeg(quantized))

    def test_fractional_float32_landmarks_use_the_saved_sampling_matrix(self):
        # Non-integer source landmarks expose NumPy float32 intermediate
        # rounding: replaying JSON/Python-float geometry can otherwise move an
        # OpenCV subpixel sampling bin even when both matrices end as float32.
        self.analysis = copy.deepcopy(type(self).analysis)
        self.analysis.faces[0].points += np.array([.56691684, .43074415], np.float32)
        result = self.process()
        self.assertIsNotNone(result.jpeg)
        self.assertEqual(result.before_jpeg, result.jpeg)
        x, y, width, height = result.measurements["crop_geometry"]["source_rect"]
        out_w, out_h = result.measurements["raw_development"]["working_size"]
        matrix = np.array([[out_w / width, 0, -x * out_w / width],
                           [0, out_h / height, -y * out_h / height]], np.float32)
        fx, fy, fw, fh = map(np.float32, (x, y, width, height))
        weak_intermediates = np.array([[np.float32(out_w) / fw, 0, -fx * np.float32(out_w) / fw],
                                      [0, np.float32(out_h) / fh, -fy * np.float32(out_h) / fh]], np.float32)
        self.assertFalse(np.array_equal(matrix, weak_intermediates))
        expected = cv2.warpAffine(self.linear, matrix, (out_w, out_h), flags=cv2.INTER_AREA,
                                  borderMode=cv2.BORDER_REPLICATE)
        digest = hashlib.sha256(expected.tobytes()).hexdigest()
        self.assertEqual(digest, result.measurements["raw_development"]["working_linear_sha256"])

    def test_crop_rotation_moves_float_and_preview_on_identical_grid(self):
        baseline = self.process()
        saved_linear, saved_preview = self.linear, self.preview
        self.linear = np.ascontiguousarray(np.rot90(saved_linear, 2))
        self.preview = np.ascontiguousarray(np.rot90(saved_preview, 2))
        rotated = self.process(crop={"rotation": 180})
        self.assertIsNotNone(rotated.jpeg)
        self.assertEqual(rotated.jpeg, baseline.jpeg)
        self.assertEqual(rotated.before_jpeg, rotated.jpeg)
        self.assertEqual(rotated.measurements["raw_development"]["working_linear_sha256"],
                         baseline.measurements["raw_development"]["working_linear_sha256"])

    def test_arbitrary_rotation_comparison_replays_exact_float_geometry(self):
        crop = dict(zoom=1.08, x=1., y=1., rotation=0, angle=-1.2)
        result = self.process(crop=crop)
        self.assertIsNotNone(result.jpeg, [c.__dict__ for c in result.checks])
        self.assertEqual(result.before_jpeg, result.jpeg)
        with patch.object(P, "get_analyzer", side_effect=AssertionError("No analysis during comparison")):
            rebuilt = comparison.render(RAW_BYTES, result.measurements, {"crop": crop}, comparison.size(result.jpeg), None)
        self.assertEqual(rebuilt, result.jpeg)

    def test_comparison_rejects_changed_decoder_settings_or_native_grid(self):
        result = self.process()
        for key, replacement in [("version", "different"), ("rawpy", "different"),
                                 ("libraw", [9, 9, 9]), ("source_sha256", "different")]:
            measurements = copy.deepcopy(result.measurements)
            measurements["raw_development"][key] = replacement
            with self.assertRaises(ValueError):
                comparison.render(RAW_BYTES, measurements, {}, comparison.size(result.jpeg), None)
        changed_report = copy.deepcopy(self.report)
        changed_report["settings"]["wb"] = "auto"
        with patch.object(P, "load_source", return_value=(self.preview, self.linear, changed_report)):
            with self.assertRaises(ValueError):
                comparison.render(RAW_BYTES, result.measurements, {}, comparison.size(result.jpeg), None)
        report = copy.deepcopy(result.measurements)
        report["analysis_size"] = [1, 1]
        with self.assertRaises(ValueError): comparison.render(RAW_BYTES, report, {}, comparison.size(result.jpeg), None)

    def test_lighting_uses_true_linear_samples_instead_of_inverse_preview(self):
        rng = np.random.default_rng(30)
        master = rng.uniform(.01, .3, size=(24, 32, 3)).astype(np.float32)
        rgb = R.render(master)
        for tone in ("neutral", "photographic"):
            rgb = R.render(master, tone)
            with patch.object(A, "_tone", side_effect=AssertionError("JPEG reconstruction used")):
                out, evidence = A.apply(rgb, None, "balanced", linear_master=master, raw_tone=tone)
            expected = R.render(master * np.float32(2 ** .5), tone)
            np.testing.assert_array_equal(out, expected)
            reconstructed = R.render(A._linear(rgb) * np.float32(2 ** .5), tone)
            self.assertGreater(np.count_nonzero(out != reconstructed), 100)
            self.assertEqual(evidence["raw_lighting"]["master_dtype"], "float32")
            self.assertEqual(evidence["decisions"]["skin_percent"], 0)
            self.assertEqual(evidence["decisions"]["maximum_highlight_reduction_ev"], 0)

    def test_ofiq_source_is_declared_raw_preview_not_sensor_container(self):
        with patch.object(config, "OFIQ_ENABLED", False):
            source_png = ofiq.source_png(RAW_BYTES, self.settings)
        with Image.open(io.BytesIO(source_png)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (1600, 2100))
            np.testing.assert_array_equal(np.asarray(image), self.preview)

    def test_ofiq_rejects_unknown_raw_and_tiff_instead_of_measuring_a_thumbnail(self):
        unsupported = RAW_BYTES[:10] + b"\x03\x00" + RAW_BYTES[12:]
        with patch.object(P.Image, "open", side_effect=AssertionError("Unsupported RAW reached Pillow")):
            with self.assertRaises(ValueError):
                ofiq.source_png(unsupported, self.settings)
        stream = io.BytesIO()
        Image.new("RGB", (64, 80), (120, 90, 70)).save(stream, "TIFF")
        with self.assertRaises(ValueError):
            ofiq.source_png(stream.getvalue())
        self.worker.assert_not_called()

    def test_ofiq_rejects_a_development_revision_different_from_the_saved_result(self):
        # Native quality must describe the result's saved development, rather
        # than silently measuring a newly installed decoder/settings revision.
        expected = copy.deepcopy(self.report)
        png = ofiq.source_png(RAW_BYTES, self.settings, expected_development=expected)
        self.assertTrue(png.startswith(b"\x89PNG"))
        for key, replacement in [("version", "changed"), ("rawpy", "changed"),
                                 ("libraw", [9, 9, 9]), ("source_sha256", "changed"),
                                 ("settings", dict(self.settings, wb="auto"))]:
            changed = dict(expected, **{key: replacement})
            with self.assertRaises(ValueError):
                ofiq.source_png(RAW_BYTES, self.settings, expected_development=changed)

    def test_missing_decoder_returns_failure_even_when_ofiq_enabled(self):
        with patch.object(R, "decode", side_effect=R.Unavailable("RAW runtime needs local setup")), \
             patch.object(config, "OFIQ_ENABLED", True), patch.object(ofiq, "assess") as assess:
            result = self.process()
        self.assertFalse(result.ok)
        self.assertIsNone(result.jpeg)
        self.assertTrue(any(c.key == "file" and c.status == "fail" for c in result.checks))
        assess.assert_not_called()


if __name__ == "__main__":
    unittest.main()
