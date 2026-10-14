"""Source invariants and real diagnostics for opt-in portrait finishing."""
import json
import hashlib
import io
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from test_hotspots import fixture
from app import enhancement, hotspots, portrait_tone, processing, skin, skin_guided, portrait_finish


class PortraitFinishTests(unittest.TestCase):
    def test_defaults_and_zero_strength_do_not_change_existing_processing(self):
        rgb, points = fixture()
        self.assertEqual(enhancement.validate()['skin_method'], 'bilateral')
        self.assertEqual(enhancement.validate()['portrait_tone'], 0)
        for operation in (portrait_tone.apply, skin_guided.apply):
            out, record = operation(rgb, points, 0)
            np.testing.assert_array_equal(out, rgb)
            self.assertEqual(record['status'], 'unchanged')

    def test_guided_keeps_source_marks_features_highlights_and_user_keep_areas(self):
        rgb, points = fixture()
        noise = np.random.default_rng(25).normal(0, 3, rgb.shape[:2])
        rgb = np.clip(rgb.astype(float) + noise[..., None], 0, 255).astype(np.uint8)
        rgb[83:95, 153:165] = (255, 170, 120)
        rgb[74:82, 133:142] = (45, 28, 20)
        keep = [[.38, .27, .03]]
        original, original_points = rgb.copy(), points.copy()
        before, _, protected, _ = skin.protection(rgb, points, keep)
        out, record = skin_guided.apply(rgb, points, 100, keep)
        np.testing.assert_array_equal(rgb, original)
        np.testing.assert_array_equal(points, original_points)
        np.testing.assert_array_equal(out[protected], rgb[protected])
        np.testing.assert_array_equal(out[before['_candidate_mask']], rgb[before['_candidate_mask']])
        np.testing.assert_array_equal(out[74:82, 133:142], rgb[74:82, 133:142])
        self.assertGreater(record['edited_pixels'], 100)
        self.assertEqual(out.shape, rgb.shape)
        self.assertTrue(record['protected_exact'])
        self.assertEqual(record['after_hotspots'], skin._diagnostic(hotspots.measure(out, points)))
        self.assertNotIn('reverted_regions', record)
        json.dumps(record)

    def test_guided_fallback_is_the_same_filter_not_a_hidden_substitution(self):
        light = np.random.default_rng(19).normal(50, 3, (40, 50)).astype(np.float32)
        expected, method = skin_guided._guided(light, 4, 16)
        if method != 'opencv-ximgproc-guided-filter':self.skipTest('Comparison needs ximgproc')
        with patch.object(cv2, 'ximgproc', None):
            actual, method = skin_guided._guided(light, 4, 16)
        np.testing.assert_allclose(actual, expected, atol=.001)
        self.assertEqual(method, 'opencv-box-guided-filter')

    def test_tone_is_local_and_preserves_existing_clipped_evidence(self):
        rgb, points = fixture()
        rgb[83:95, 153:165] = 255
        mask = np.zeros(rgb.shape[:2], np.float32)
        mask[30:295, 55:265] = 1
        original = rgb.copy()
        out, record = portrait_tone.apply(rgb, points, 100, mask)
        np.testing.assert_array_equal(rgb, original)
        np.testing.assert_array_equal(out[mask == 0], rgb[mask == 0])
        np.testing.assert_array_equal(out[83:95, 153:165], rgb[83:95, 153:165])
        self.assertEqual(out.shape, rgb.shape)
        self.assertGreater(record['edited_pixels'], 100)
        self.assertGreater(record['after_hotspots']['regions'][0]['near_clip_all_percent'], 0)
        self.assertEqual(record['after_hotspots'], skin._diagnostic(hotspots.measure(out, points, mask)))
        neutral, _ = portrait_tone.apply(rgb, points, 100, mask, (248, 248, 248))
        np.testing.assert_array_equal(neutral[mask == 0], np.tile([248, 248, 248], ((mask == 0).sum(), 1)))
        json.dumps(record)

    def test_invalid_regions_and_options_are_rejected_or_reported_unavailable(self):
        rgb, points = fixture()
        for operation in (portrait_tone.apply, skin_guided.apply):
            for strength in (-1, 101, float('nan')):
                with self.assertRaises(ValueError):operation(rgb, points, strength)
            with self.assertRaises(ValueError):operation(rgb, points[:20], 50)
        with self.assertRaises(ValueError):enhancement.validate({'skin_method':'fake'})
        values, checks = {}, []
        out = processing._portrait_tone(rgb, None, None, {'portrait_tone':50}, values, checks)
        np.testing.assert_array_equal(out, rgb)
        self.assertEqual(checks[0].status, 'warn')
        self.assertEqual(values['local_enhancement']['stages'][0]['status'], 'unavailable')

    def test_full_frame_runs_new_stages_and_checks_the_actual_encoded_output(self):
        rgb, points = fixture()
        buffer=io.BytesIO();Image.fromarray(rgb).save(buffer,'PNG')
        class Analyzer:
            def analyze(self, pixels):
                return processing.Analysis([processing.FaceData(points,{})], np.ones(pixels.shape[:2],np.float32))
        result=processing.process(buffer.getvalue(),analyzer=Analyzer(),print_only=True,
            auto_adjust=False,fix_shadows=False,even_bg=False,replace_bg=False,
            enhancement_options={'skin_method':'guided','skin':70,'portrait_tone':100})
        self.assertIsNotNone(result.jpeg)
        stages=result.measurements['local_enhancement']['stages']
        self.assertEqual([s['phase'] for s in stages],['portrait_tone','skin'])
        self.assertTrue(all(s['status']=='applied' for s in stages))
        self.assertFalse(result.ok)
        self.assertEqual(result.measurements['final_highlights']['image_sha256'],hashlib.sha256(result.jpeg).hexdigest())

    def test_tone_alone_finds_landmarks_in_a_freestyle_profile(self):
        profile=next(c for c in processing.photomatic.COUNTRIES.values() if not c['use_head'] and not c['use_width'])
        rgb, points=fixture();buffer=io.BytesIO();Image.fromarray(rgb).save(buffer,'PNG')
        class Analyzer:
            def analyze(self,pixels):
                return processing.Analysis([processing.FaceData(points,{})],None)
        result=processing.process(buffer.getvalue(),country_id=profile['id'],analyzer=Analyzer(),
            auto_adjust=False,fix_shadows=False,even_bg=False,replace_bg=False,
            enhancement_options={'portrait_tone':100})
        self.assertEqual(result.measurements['face_analysis']['face_count'],1)
        self.assertEqual(result.measurements['local_enhancement']['stages'][0]['status'],'applied')


class RelativeHighlightTests(unittest.TestCase):
    def shine_fixture(self, colour=(165, 130, 110)):
        rgb, points = fixture(colour)
        y, x = np.indices(rgb.shape[:2])
        patch = np.exp(-((x-160)**2+(y-88)**2)/(2*10**2))
        linear = portrait_finish._linear(rgb)
        # An unclipped, moderately bright and less chromatic local reflection.
        linear += patch[..., None]*.16
        rgb = np.rint(np.clip(np.where(linear <= .0031308, linear*12.92, 1.055*linear**(1/2.4)-.055), 0, 1)*255).astype(np.uint8)
        return rgb, points

    def test_uniform_dark_mid_and_light_faces_are_exact_no_ops(self):
        for colour in ((65, 45, 35), (165, 130, 110), (230, 210, 190)):
            rgb, points = fixture(colour)
            analysis = portrait_finish.analyse(rgb, points)
            out, stage = portrait_finish.apply_highlights(rgb, analysis, {'max_highlight_ev': .3})
            np.testing.assert_array_equal(out, rgb)
            self.assertEqual(analysis['report']['relative_highlight_pixels'], 0)
            self.assertEqual(stage['status'], 'unchanged')
            self.assertEqual(analysis['report']['texture_need'], 0)

    def test_moderate_relative_shine_is_reduced_without_source_or_geometry_mutation(self):
        for colour in ((65, 45, 35), (165, 130, 110), (230, 210, 190)):
            rgb, points = self.shine_fixture(colour); original = rgb.copy(); geometry = points.copy()
            analysis = portrait_finish.analyse(rgb, points)
            out, stage = portrait_finish.apply_highlights(rgb, analysis, {'max_highlight_ev': .2})
            self.assertGreater(analysis['report']['relative_highlight_pixels'], 0)
            self.assertLess(out[88, 160].mean(), rgb[88, 160].mean())
            self.assertEqual(stage['status'], 'applied')
            self.assertLessEqual(stage['maximum_highlight_ev'], .2)
            np.testing.assert_array_equal(rgb, original);np.testing.assert_array_equal(points, geometry)
            oval = hotspots._polygon_mask(rgb.shape[:2], points[hotspots.FACE_OVAL])
            np.testing.assert_array_equal(out[~oval], rgb[~oval])
            json.dumps(analysis['report']);json.dumps(stage)

    def test_clipped_channels_stay_exact_and_are_not_reported_recovered(self):
        rgb, points = self.shine_fixture();rgb[85:90, 154:159] = (255, 170, 120)
        analysis = portrait_finish.analyse(rgb, points)
        out, stage = portrait_finish.apply_highlights(rgb, analysis, .3)
        np.testing.assert_array_equal(out[85:90, 154:159], rgb[85:90, 154:159])
        self.assertEqual(stage['saturated_channel_pixels_remaining'], 25)
        self.assertTrue(stage['current_near_clip_pixels_retained_exact'])
        self.assertEqual(analysis['report']['saturated_source_channel_pixels'], 25)

    def test_same_scalar_gain_retains_fine_detail_and_channel_ratios(self):
        rgb, points = self.shine_fixture()
        y, x = np.indices(rgb.shape[:2]);grain = ((x+y)%2*2-1)*2
        rgb = np.clip(rgb.astype(int)+grain[..., None], 0, 249).astype(np.uint8)
        analysis = portrait_finish.analyse(rgb, points)
        out, _ = portrait_finish.apply_highlights(rgb, analysis, .2)
        gain = portrait_finish.highlight_gain(analysis, rgb.shape[:2], .2)
        expected = portrait_finish._linear(rgb)*gain[..., None]
        # The only discrepancy is the final 8-bit quantization, including pores.
        self.assertLess(float(np.max(np.abs(portrait_finish._linear(out)-expected))), .006)
        log_source = np.log2(np.maximum(portrait_finish._linear(rgb).mean(axis=2), 1e-5))
        log_out = np.log2(np.maximum(portrait_finish._linear(out).mean(axis=2), 1e-5))
        high = lambda a:a-cv2.GaussianBlur(a, (0, 0), 1.2)
        region = np.s_[76:100, 148:172]
        projection = np.mean(high(log_source)[region]*high(log_out)[region])/np.mean(high(log_source)[region]**2)
        self.assertGreater(projection, .94)

    def test_source_marks_and_features_are_separate_from_tonal_support(self):
        rgb, points = self.shine_fixture();rgb[83:87, 133:137] = (45, 28, 20)
        analysis = portrait_finish.analyse(rgb, points, keep=[[.57, .30, .03]])
        self.assertTrue(analysis['_mark_mask'][84, 134])
        self.assertTrue(analysis['_feature_mask'][130, 125])
        self.assertEqual(analysis['_cleanup_alpha'][84, 134], 0)
        self.assertEqual(analysis['_cleanup_alpha'][130, 125], 0)
        self.assertGreater(analysis['_face_alpha'][130, 125], 0)
        self.assertEqual(analysis['_cleanup_alpha'][96, 182], 0)

    def test_analysis_field_can_be_reused_at_a_larger_native_grid(self):
        rgb, points = self.shine_fixture();analysis = portrait_finish.analyse(rgb, points)
        larger = cv2.resize(rgb, (640, 640), interpolation=cv2.INTER_NEAREST)
        out, stage = portrait_finish.apply_highlights(larger, analysis, .2)
        self.assertEqual(out.shape, larger.shape)
        self.assertEqual(stage['source_size'], [640, 640])
        self.assertGreater(stage['edited_pixels'], 0)
        for invalid in (-1, float('nan'), 2):
            with self.assertRaises(ValueError):portrait_finish.highlight_gain(analysis, rgb.shape[:2], invalid)


if __name__ == '__main__':unittest.main()
