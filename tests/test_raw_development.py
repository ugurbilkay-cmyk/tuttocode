"""Sensor transport and float development invariants using synthetic RAW mocks.

Customer photographs are exercised privately, never packaged as test fixtures.
"""
from collections import namedtuple
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import raw_development as R


def envelope():
    return b"II*\x00\x10\x00\x00\x00CR\x02\x00\x00\x00\x00\x00synthetic-container"


class RawDevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / "input.cr2"; self.source.write_bytes(envelope())
        R.clear_cache(); self.addCleanup(R.clear_cache)

    def fake_decoder(self):
        Sizes = namedtuple("Sizes", "raw_width raw_height width height flip top_margin left_margin")
        self.raw = SimpleNamespace(
            sizes=Sizes(8, 6, 4, 3, 0, 2, 2), auto_whitebalance=[1., .5, .25, .5],
            black_level_per_channel=[512, 512, 512, 512], white_level=16383,
            camera_white_level_per_channel=[15300, 15300, 15300, 15300])
        self.rgb16 = np.array([[[12500, 13300, 15000], [12501, 13301, 15001],
                                [65535, 32000, 17000], [20, 0, 1800]]] * 3, dtype=np.uint16)
        def postprocess(**params):
            self.params = params
            return self.rgb16.copy()
        self.raw.postprocess = postprocess
        self.raw.open_file = lambda source: None
        self.raw.unpack = lambda: setattr(self, "unpacked", True)
        class Context:
            def __enter__(inner): return self.raw
            def __exit__(inner, *args): return False
        return SimpleNamespace(__version__=R.RAWPY_VERSION, libraw_version=(0, 22, 1),
                               RawPy=lambda: Context(), ColorSpace=SimpleNamespace(sRGB="sRGB"),
                               HighlightMode=SimpleNamespace(Ignore="Ignore"),
                               DemosaicAlgorithm=SimpleNamespace(AHD="AHD"),
                               FBDDNoiseReductionMode=SimpleNamespace(Off="Off"))

    def response(self, args, **kwargs):
        out = Path(args[args.index("--output") + 1])
        source = Path(args[args.index("--input") + 1])
        settings = json.loads(args[args.index("--settings") + 1])
        result = R._decode_native(source, settings, self.fake_decoder())
        np.save(out / "linear.npy", result.linear)
        np.save(out / "preview.npy", result.preview)
        (out / "report.json").write_text(json.dumps(result.report))
        self.last_output = out
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def test_sensor_envelope_is_not_filename_or_embedded_preview(self):
        self.assertTrue(R.is_raw_signature(envelope()))
        self.assertTrue(R.is_raw_signature(b"MM\x00*" + envelope()[4:]))
        for invalid in [b"", b"II*\x00" * 4, b"\xff\xd8JPEG" * 4, envelope()[:11]]:
            self.assertFalse(R.is_raw_signature(invalid))
        renamed = self.root / "not-a-photo.jpg"; renamed.write_bytes(envelope())
        self.assertEqual(R.check_source(renamed), renamed)
        self.source.write_bytes(b"\xff\xd8JPEG thumbnail" * 2)
        with patch.object(R.subprocess, "run") as worker:
            with self.assertRaises(R.InvalidRaw): R.decode(self.source, data_dir=self.root)
            worker.assert_not_called()

    def test_known_canon_container_is_recognised_before_version_validation(self):
        self.assertTrue(R.is_raw_container(envelope()))
        unknown_version = envelope()[:10] + b"\x03\x00" + envelope()[12:]
        self.assertTrue(R.is_raw_container(unknown_version))
        self.assertFalse(R.is_raw_signature(unknown_version))
        self.assertTrue(R.is_raw_container(unknown_version[:12]))
        self.assertFalse(R.is_raw_signature(unknown_version[:12]))
        for invalid in [b"", b"II*\x00" * 4, b"\xff\xd8JPEG" * 4,
                        b"not-a-tiffCR" + b"\x02\x00", envelope()[:11]]:
            self.assertFalse(R.is_raw_container(invalid))
        self.source.write_bytes(unknown_version)
        with self.assertRaises(R.InvalidRaw):
            R.check_source(self.source)

    def test_exposure_wb_and_tone_are_explicit_and_bounded(self):
        for settings in [dict(wb="adobe"), dict(tone="hidden-auto"), dict(exposure_ev=True),
                         dict(exposure_ev="bad"), dict(exposure_ev=float("nan")),
                         dict(exposure_ev=float("inf")), dict(exposure_ev=-2.1), dict(exposure_ev=3.1)]:
            with self.assertRaises(R.InvalidRaw): R.RawSettings(**settings)
        self.assertEqual(R.RawSettings(exposure_ev="1.95").exposure_ev, 1.95)

    def test_genuine_float_master_retains_sub_byte_values_and_above_one(self):
        source_before = self.source.read_bytes()
        result = R._decode_native(self.source, R.RawSettings(exposure_ev=1.), self.fake_decoder())
        self.assertEqual(result.linear.dtype, np.float32)
        self.assertGreater(result.linear.max(), 1.)
        self.assertNotEqual(result.linear[0, 0, 0], result.linear[0, 1, 0])
        np.testing.assert_allclose(result.linear, self.rgb16.astype(np.float32) * 8 / 65535, atol=1e-6)
        self.assertEqual(result.report["explicit_wb_normalization_scale"], 4.)
        self.assertEqual(result.report["decoder_ceiling_pixels"], 3)
        self.assertTrue(self.params["no_auto_bright"])
        self.assertFalse(self.params["no_auto_scale"])
        self.assertEqual(self.params["gamma"], (1, 1))
        self.assertEqual(self.params["median_filter_passes"], 0)
        self.assertEqual(self.source.read_bytes(), source_before)

    def test_tone_changes_preview_only_and_uses_common_channel_gain(self):
        master = np.array([[[.05, .1, .2], [3., 1.5, 1.]]], np.float32)
        before = master.copy()
        neutral = R.render(master, "neutral"); photo = R.render(master, "photographic")
        np.testing.assert_array_equal(master, before)
        np.testing.assert_array_equal(neutral[:, :1], photo[:, :1])
        self.assertLess(photo[0, 1, 0], 255)
        self.assertFalse(np.array_equal(neutral, photo))
        for invalid in [np.full((2, 2, 3), np.nan), np.zeros((2, 2)), -np.ones((2, 2, 3))]:
            with self.assertRaises(R.InvalidRaw): R.render(invalid)

    def test_native_sensor_limits_checked_before_demosaic(self):
        decoder = self.fake_decoder()
        self.raw.sizes = self.raw.sizes._replace(raw_width=50000)
        with self.assertRaises(R.InvalidRaw): R._decode_native(self.source, {}, decoder)
        self.assertFalse(hasattr(self, "params"))
        self.assertFalse(hasattr(self, "unpacked"))

    def test_cache_key_includes_wb_exposure_tone_and_source_and_is_bounded(self):
        with patch.object(R.subprocess, "run", side_effect=self.response) as worker:
            a = R.decode(self.source, data_dir=self.root)
            b = R.decode(self.source, data_dir=self.root)
            self.assertFalse(a.report["cache_hit"]); self.assertTrue(b.report["cache_hit"])
            self.assertEqual(worker.call_count, 1)
            with self.assertRaises(ValueError): a.linear[0, 0, 0] = 0
            with self.assertRaises(ValueError): a.linear.setflags(write=True)
            a.report["settings"]["wb"] = "mutated"
            self.assertEqual(b.report["settings"]["wb"], "camera")
            for settings in [dict(wb="auto"), dict(wb="auto", exposure_ev=1),
                             dict(wb="auto", exposure_ev=1, tone="photographic")]:
                R.decode(self.source, settings, data_dir=self.root)
            self.source.write_bytes(envelope() + b"changed")
            R.decode(self.source, settings, data_dir=self.root)
            self.assertEqual(worker.call_count, 5)
            R.decode(self.source, data_dir=self.root)
            self.assertEqual(worker.call_count, 6)  # one entry, not an unbounded photo cache
        self.assertFalse(self.last_output.exists())

    def test_missing_dependency_timeout_and_native_failure_are_explicit(self):
        for outcome, expected in [(subprocess.CompletedProcess([], 3, b"", b"private-name"), "unavailable"),
                                  (subprocess.CompletedProcess([], 4, b"", b"private-name"), "could not"),
                                  (subprocess.TimeoutExpired(["private-name"], .1), "timed out")]:
            with patch.object(R.subprocess, "run", side_effect=outcome if isinstance(outcome, Exception) else None,
                              return_value=outcome):
                with self.assertRaises(R.Unavailable) as caught: R.decode(self.source, data_dir=self.root)
                self.assertIn(expected, str(caught.exception)); self.assertNotIn("private", str(caught.exception))
        decoder = self.fake_decoder(); decoder.__version__ = "unexpected"
        with self.assertRaises(R.Unavailable): R._decode_native(self.source, {}, decoder)

    def test_secret_free_environment_and_corrupt_transport_rejected(self):
        with patch.dict(os.environ, OPENAI_API_KEY="secret", ADMIN_PASSWORD="secret", SMTP_PASSWORD="secret"):
            env = R._worker_environment()
        self.assertFalse(any(k in env for k in ["OPENAI_API_KEY", "ADMIN_PASSWORD", "SMTP_PASSWORD"]))
        def corrupt(args, **kwargs):
            self.response(args, **kwargs)
            out = Path(args[args.index("--output") + 1])
            report = json.loads((out / "report.json").read_text()); report["source_sha256"] = "wrong"
            (out / "report.json").write_text(json.dumps(report))
            return subprocess.CompletedProcess(args, 0, b"", b"")
        with patch.object(R.subprocess, "run", side_effect=corrupt):
            with self.assertRaises(R.Unavailable): R.decode(self.source, data_dir=self.root)


if __name__ == "__main__":
    unittest.main()
