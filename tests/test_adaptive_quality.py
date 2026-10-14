"""Adaptive decisions, source-detail rollback and staff-intent routing."""
import io
import json
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from test_hotspots import fixture
from app import adaptive_quality as A, enhancement as E, main, processing as P, config


class AdaptiveTests(unittest.TestCase):
    def test_clean_uniform_complexions_with_bright_background_are_exact_no_ops(self):
        for colour in ((65,45,35),(165,130,110),(230,210,190)):
            rgb,points=fixture(colour);rgb[:25]=235
            for profile in A.PROFILES:
                with patch.object(E,'apply') as worker:
                    out,e=A.apply(rgb,points,profile)
                    worker.assert_not_called()
                np.testing.assert_array_equal(out,rgb)
                self.assertEqual(e['status'],'applied')
                self.assertEqual(e['decisions']['exposure_ev'],0)
                self.assertEqual(e['decisions']['skin_percent'],0)
                json.dumps(e)

    def test_exposure_is_bounded_scene_based_and_no_new_clip_is_created(self):
        rgb,points=fixture((45,35,25));rgb[90:100,160:170]=255
        # Too small a highlight patch to conceal a globally dark frame.
        original=rgb.copy()
        for profile,budget in A.PROFILES.items():
            with patch.object(E,'apply') as worker:
                out,e=A.apply(rgb,points,profile)
                worker.assert_not_called()
            self.assertGreater(e['decisions']['exposure_ev'],0)
            self.assertLessEqual(e['decisions']['exposure_ev'],budget['exposure_ev'])
            np.testing.assert_array_equal(out[90:100,160:170],rgb[90:100,160:170])
            self.assertFalse(((out.max(axis=2)>=250)&(rgb.max(axis=2)<250)).any())
        np.testing.assert_array_equal(original,rgb)

    def test_region_variation_selects_lighting_without_whitening_uniform_skin(self):
        rgb,points=fixture();rgb[:25]=235
        rgb[:,70:145]=np.rint(rgb[:,70:145]*.65).astype(np.uint8)
        out,e=A.apply(rgb,points,'balanced')
        self.assertGreater(e['decisions']['maximum_local_shadow_ev'],0)
        self.assertEqual(e['decisions']['exposure_ev'],0)
        self.assertEqual(out.shape,rgb.shape)

    def test_cleanup_is_selected_by_residuals_and_failure_is_not_reported_as_applied(self):
        rgb,points=fixture();rgb[:25]=235
        noise=np.random.default_rng(6).normal(0,4,rgb.shape[:2])
        rgb=np.clip(rgb.astype(float)+noise[...,None],0,255).astype(np.uint8)
        with patch.object(E,'apply',side_effect=lambda r,v:(r,dict(status='unavailable',models=[],message='Test failure'))) as worker:
            out,e=A.apply(rgb,points,'balanced')
        self.assertEqual(worker.call_count,2) # lighting proposal plus noise cleanup
        self.assertGreater(e['decisions']['denoise_percent'],0)
        self.assertEqual(e['status'],'partial')
        self.assertEqual(e['stages'][0]['status'],'unavailable')
        self.assertIn('texture_guard',e)

    def test_lighting_prediction_is_cached_once_and_nn_texture_is_discarded(self):
        rgb,points=fixture((80,60,45));rgb[:25]=235
        ramp=np.linspace(.3,1,rgb.shape[1])[None,:,None]
        rgb=np.rint(rgb*ramp).astype(np.uint8)
        # Source texture/geometry must survive even a flat NN proposal.
        rgb[100:112,110:122]=[45,35,25]
        A._lighting_cache=None
        try:
            with patch.object(E,'apply',side_effect=lambda r,v:(np.full_like(r,230),
                dict(status='applied',models=[dict(engine='retinex',model_sha256='synthetic')],phase='restore'))) as worker:
                outputs=[]
                for key in A.PROFILES:
                    out,e=A.apply(rgb,points,key);outputs.append(out)
                    self.assertTrue(e['decisions']['lighting_adviser_requested'])
                    self.assertLessEqual(e['decisions']['maximum_learned_lighting_ev'],A.PROFILES[key]['exposure_ev']+.0001)
                    self.assertEqual(e['stages'][0]['cache_hit'],key!='natural')
                    # The original dark mark survives lighting, rather than
                    # becoming the synthetic white image supplied by the NN.
                    self.assertLess(out[105,115,0],out[105,130,0])
                self.assertEqual(worker.call_count,1)
                self.assertGreater(outputs[-1].mean(),outputs[0].mean())
        finally:A._lighting_cache=None

    def test_painted_candidate_is_blended_back_and_guard_reports_actual_final_projection(self):
        rng=np.random.default_rng(7)
        rgb=np.clip(140+rng.normal(0,6,(160,180,3)),0,255).astype(np.uint8)
        painted=cv2.GaussianBlur(rgb,(0,0),4)
        out,e=A.texture_guard(rgb,painted,np.ones(rgb.shape[:2],bool),.90)
        self.assertLess(e['blend'],.25)
        self.assertGreaterEqual(e['minimum_final_projection'],.895)
        self.assertLess(np.mean(np.abs(out.astype(float)-rgb)),np.mean(np.abs(painted.astype(float)-rgb)))

    def test_unknown_or_missing_geometry_is_not_invented(self):
        rgb,points=fixture()
        with self.assertRaises(ValueError):A.apply(rgb,points,'unknown')
        for invalid in (None,points[:100],points*np.nan,np.zeros((478,2))):
            out,e=A.apply(rgb,invalid,'balanced')
            np.testing.assert_array_equal(out,rgb);self.assertEqual(e['status'],'unavailable')
        with self.assertRaises(ValueError):E.validate({'adaptive_profile':'invented'})

    def test_staff_form_routes_intent_and_ignores_old_fixed_stack(self):
        with patch.object(main.background,'choices',return_value=[{'key':'hr','installed':True}]):
            options=main._opts({'opts':'1','adaptive_profile':'balanced','enhancer_skin':'100',
                'enhancer_lighting':'80','auto_adjust':'on','fix_shadows':'on','exposure':'1.5'})
        self.assertEqual(options['enhancement_options']['adaptive_profile'],'balanced')
        self.assertEqual(options['enhancement_options']['skin'],0)
        self.assertFalse(options['auto_adjust']);self.assertFalse(options['fix_shadows'])
        self.assertFalse(any(options['adjustments'].values()))
        self.assertEqual(options['background_engine'],'hr')

    def test_full_frame_processing_calls_controller_once_without_legacy_stack(self):
        rgb,points=fixture();rgb[:25]=235
        stream=io.BytesIO();Image.fromarray(rgb).save(stream,'PNG')
        class Analyzer:
            def analyze(self,rgb):return P.Analysis([P.FaceData(points,{})],np.ones(rgb.shape[:2],np.float32))
        with patch.object(config,'OFIQ_ENABLED',False),patch.object(A,'apply',wraps=A.apply) as controller, \
             patch.object(P,'enhance') as old,patch.object(P,'soften_face_shadows') as shadow,patch.object(E,'apply') as learned:
            result=P.process(stream.getvalue(),analyzer=Analyzer(),print_only=True,auto_adjust=True,fix_shadows=True,
                even_bg=False,replace_bg=False,enhancement_options={'adaptive_profile':'balanced','lighting':100,'skin':100})
        self.assertIsNotNone(result.jpeg);self.assertEqual(controller.call_count,1)
        old.assert_not_called();shadow.assert_not_called();learned.assert_not_called()
        self.assertEqual(result.measurements['adaptive_quality']['profile'],'balanced')
        self.assertIn('image_sha256',result.measurements['final_highlights'])
        # A full-frame photo has no invented passport approval.
        self.assertFalse(result.ok)


if __name__=='__main__':unittest.main()
