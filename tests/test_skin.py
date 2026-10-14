"""Texture smoothing without changing protected features or highlight findings."""
import io
import hashlib
import json
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image
from test_hotspots import fixture
from app import skin,hotspots,processing as P,main,enhancement as E


class SkinTests(unittest.TestCase):
    def test_zero_strength_is_an_exact_no_op(self):
        rgb,points=fixture();out,record=skin.apply(rgb,points,0)
        np.testing.assert_array_equal(out,rgb);self.assertEqual(record['status'],'unchanged')

    def test_texture_reduces_without_geometry_or_source_mutation(self):
        rgb,points=fixture()
        rng=np.random.default_rng(19)
        noise=rng.normal(0,2,rgb.shape[:2]).astype(np.int16)
        rgb=np.clip(rgb.astype(np.int16)+noise[...,None],0,255).astype(np.uint8)
        original=rgb.copy();out,record=skin.apply(rgb,points,100)
        self.assertEqual(out.shape,rgb.shape);np.testing.assert_array_equal(rgb,original)
        self.assertGreater(record['edited_pixels'],100)
        self.assertLess(out[180:205,100:120,0].std(),rgb[180:205,100:120,0].std())
        self.assertLess(abs(record['mean_skin_lightness_change']),.2)

    def test_hotspot_pixels_counts_peaks_and_clipped_channels_are_preserved(self):
        for colour in ((65,45,35),(165,130,110),(230,210,190)):
            rgb,points=fixture(colour)
            noise=np.random.default_rng(5).integers(-2,3,rgb.shape[:2])
            rgb=np.clip(rgb.astype(int)+noise[...,None],0,255).astype(np.uint8)
            rgb[85:95,155:165]=(255,170,120)
            rgb[165:173,110:120]=255
            rgb[180:185,205:210]=(240,235,230)
            before=hotspots.measure(rgb,points,include_masks=True)
            out,record=skin.apply(rgb,points,100)
            after=hotspots.measure(out,points)
            np.testing.assert_array_equal(out[before['_candidate_mask']],rgb[before['_candidate_mask']])
            for a,b in zip(before['regions'],after['regions']):
                for key in ('peak_lightness','bright_percent','near_clip_any_percent','near_clip_all_percent'):
                    self.assertEqual(a.get(key),b.get(key),(colour,a['key'],key))
            self.assertEqual(before['patch_count'],after['patch_count'])
            self.assertTrue(record['preserved_hotspot_pixels'])

    def test_eyes_lips_face_boundary_and_background_remain_exact(self):
        rgb,points=fixture()
        rgb[120:140,110:140]=[90,50,30]
        cv2.ellipse(rgb,(160,225),(20,5),0,0,360,(230,170,180),-1)
        out,_=skin.apply(rgb,points,100)
        for ys,xs in [(slice(120,140),slice(110,140)),(slice(221,229),slice(145,175)),
                      (slice(0,20),slice(None)),(slice(None),slice(0,20))]:
            np.testing.assert_array_equal(out[ys,xs],rgb[ys,xs])

    def test_bad_landmarks_do_not_produce_a_fake_success(self):
        rgb,points=fixture()
        for invalid in (points[:100],points*np.nan,np.zeros((478,2))):
            with self.assertRaises(ValueError):skin.apply(rgb,invalid,50)
        checks=[];metrics={}
        out=P._smooth_skin(rgb,None,{'skin':50},metrics,checks)
        np.testing.assert_array_equal(out,rgb)
        self.assertEqual(checks[0].status,'warn');self.assertEqual(metrics['local_enhancement']['stages'][0]['status'],'unavailable')

    def test_full_frame_applies_skin_without_calling_a_neural_worker(self):
        rgb,points=fixture();buffer=io.BytesIO();Image.fromarray(rgb).save(buffer,'PNG')
        class Analyzer:
            def analyze(self,rgb):return P.Analysis([P.FaceData(points,{})],np.ones(rgb.shape[:2],np.float32))
        with patch.object(E.subprocess,'run') as worker:
            result=P.process(buffer.getvalue(),analyzer=Analyzer(),print_only=True,auto_adjust=False,fix_shadows=False,
                             replace_bg=False,even_bg=False,enhancement_options={'skin':70})
            worker.assert_not_called()
        self.assertIsNotNone(result.jpeg);self.assertFalse(result.ok)
        self.assertEqual(result.measurements['local_enhancement']['stages'][0]['phase'],'skin')
        self.assertIn('before_hotspots',result.measurements['local_enhancement']['stages'][0])
        self.assertEqual(result.measurements['final_highlights']['image_sha256'],hashlib.sha256(result.jpeg).hexdigest())
        json.dumps(result.measurements)  # Internal arrays must not leak into saved diagnostics.

    def test_code_check_diagnostics_reference_exact_delivered_jpeg(self):
        rgb,points=fixture();buffer=io.BytesIO();Image.fromarray(rgb).save(buffer,'JPEG')
        jpeg=buffer.getvalue()
        measured=dict(status='diagnostic',image_sha256=hashlib.sha256(jpeg).hexdigest(),near_clip_all_percent=0.,patch_count=0)
        with patch.object(P,'process',return_value=P.Result(True,[],measurements={})),patch.object(hotspots,'inspect_photo',return_value=measured) as inspector:
            result=P.check_code_photo(jpeg,P.photomatic.country()['id'],'adult')
        inspector.assert_called_once_with(jpeg,None)
        self.assertEqual(result.measurements['final_highlights']['image_sha256'],hashlib.sha256(jpeg).hexdigest())


if __name__=='__main__':unittest.main()
