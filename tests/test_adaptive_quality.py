"""Explicit scene exposure, source-only local lighting and staff routing."""
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
    def subtle_portrait(self):
        rgb,points=fixture((160,125,105))
        rgb=np.rint(rgb*np.linspace(.80,1.10,rgb.shape[1])[None,:,None]).astype(np.uint8)
        rgb[:25]=235
        return rgb,points

    def test_three_choices_apply_ordered_scene_exposure_to_different_uniform_complexions(self):
        for colour in ((65,45,35),(165,130,110),(230,210,190)):
            rgb,points=fixture(colour);rgb[:25]=235
            means=[]
            for profile,ev in [('natural',.25),('balanced',.50),('recovery',.75)]:
                with patch.object(A,'lighting_prediction') as worker:
                    out,e=A.apply(rgb,points,profile)
                worker.assert_not_called()
                self.assertEqual(e['decisions']['exposure_ev'],ev)
                self.assertEqual(e['mode'],'lighting_only')
                self.assertEqual(e['status'],'applied')
                # Common exposure reaches the neck/background as well as face.
                self.assertTrue(np.all(out[-1]>rgb[-1]))
                self.assertTrue(np.all(out[10]>rgb[10]))
                means.append(float(out[160,160].mean()))
                json.dumps(e)
            self.assertLess(means[0],means[1]);self.assertLessEqual(means[1],means[2])
            if colour[0]<200:self.assertLess(means[1],means[2])

    def test_whole_scene_gain_is_not_limited_by_the_face_oval(self):
        rgb,points=fixture((100,80,60))
        out,e=A.apply(rgb,points,'balanced')
        # Uniform illumination receives the same RGB result at face and neck.
        np.testing.assert_array_equal(out[160,160],out[310,160])
        np.testing.assert_array_equal(out[160,160],out[15,15])
        self.assertGreater(int(out[310,160,0]),int(rgb[310,160,0]))
        self.assertEqual(e['requested_scene_exposure_ev'],.5)
        self.assertIn('Whole source crop',e['decisions']['exposure_support'])

    def test_constant_model_brightness_is_removed_instead_of_hitting_a_face_cap(self):
        rgb,points=self.subtle_portrait()
        rgb[100:110,155:165]=[45,30,20]
        model=dict(status='applied',models=[])
        expected=A._tone(rgb,np.full(rgb.shape[:2],2**.5,np.float32))
        for bias in (0.,.5,2.5):
            def constant(ev,weight,valid,sigma):
                return np.full(ev.shape,bias,np.float32)
            with patch.object(A,'lighting_prediction',return_value=(np.full_like(rgb,230),model)), \
                 patch.object(A,'_lighting_field',side_effect=constant):
                out,e=A.apply(rgb,points,'balanced')
            np.testing.assert_array_equal(out,expected)
            self.assertEqual(e['decisions']['removed_model_common_ev'],bias)
            self.assertEqual(e['decisions']['maximum_learned_lighting_ev'],0)
            # The network's flat pixels never replace the source dark detail.
            self.assertLess(int(out[105,160,0]),int(out[105,185,0]))

    def test_local_field_is_identical_across_choices_and_only_scene_ev_changes(self):
        rgb,points=self.subtle_portrait();gains=[]
        def variable(ev,weight,valid,sigma):
            return np.broadcast_to(np.linspace(1.,3.,ev.shape[1],dtype=np.float32),ev.shape).copy()
        original=A._tone
        def capture(image,gain):
            gains.append(gain.copy());return original(image,gain)
        for profile in A.PROFILES:
            with patch.object(A,'lighting_prediction',return_value=(rgb,dict(status='applied',models=[]))), \
                 patch.object(A,'_lighting_field',side_effect=variable),patch.object(A,'_tone',side_effect=capture):
                _,e=A.apply(rgb,points,profile)
            self.assertGreater(e['decisions']['maximum_learned_lighting_ev'],0)
            self.assertLessEqual(e['decisions']['maximum_learned_lighting_ev'],.5)
        residuals=[np.log2(gain)-A.PROFILES[key]['exposure_ev'] for key,gain in zip(A.PROFILES,gains)]
        np.testing.assert_allclose(residuals[0],residuals[1],atol=3e-7)
        np.testing.assert_allclose(residuals[1],residuals[2],atol=3e-7)

    def test_no_retouching_shine_noise_analysis_or_spatial_filter_is_selected(self):
        rgb,points=self.subtle_portrait()
        texture=5*np.sin(np.arange(rgb.shape[1])*np.pi/3)[None,:,None]
        rgb=np.clip(np.rint(rgb+texture),0,249).astype(np.uint8)
        forbidden=AssertionError('Retouching must stay off')
        with patch.object(A,'lighting_prediction',return_value=(rgb,dict(status='applied',models=[]))), \
             patch.object(A.portrait_finish,'analyse',side_effect=forbidden), \
             patch.object(A.portrait_finish,'apply_highlights',side_effect=forbidden), \
             patch.object(A.skin_guided,'apply',side_effect=forbidden), \
             patch.object(A.blemishes,'apply',side_effect=forbidden),patch.object(A,'_noise',side_effect=forbidden):
            out,e=A.apply(rgb,points,'balanced')
        self.assertEqual(out.shape,rgb.shape)
        self.assertTrue(all(e['decisions'][name]==0 for name in
            ('denoise_percent','skin_percent','skin_cleaning_percent','sharpening','maximum_highlight_reduction_ev')))
        self.assertNotIn('feature_detail_guard',e)
        self.assertNotIn('texture_guard',e)
        self.assertEqual([s['phase'] for s in e['stages']],['adaptive_lighting'])

    def test_lighting_retains_source_clipping_and_creates_no_new_clipping(self):
        rgb,points=self.subtle_portrait()
        rgb[85:95,155:165]=[250,240,220]
        rgb[100:110,155:165]=[249,240,220]
        before=rgb.copy()
        for profile in A.PROFILES:
            with patch.object(A,'lighting_prediction',return_value=(np.full_like(rgb,245),dict(status='applied',models=[]))):
                out,e=A.apply(rgb,points,profile)
            clipped=rgb.max(axis=2)>=250
            np.testing.assert_array_equal(out[clipped],rgb[clipped])
            self.assertFalse(((out.max(axis=2)>=250)&~clipped).any())
            self.assertTrue(e['source_clipping_exact'])
            self.assertEqual(e['new_near_clip_pixels'],0)
            self.assertGreater(e['headroom_limited_pixels'],0)
        np.testing.assert_array_equal(rgb,before)

    def test_unavailable_model_retains_selected_scene_exposure_and_reports_partial(self):
        rgb,points=self.subtle_portrait()
        with patch.object(A,'lighting_prediction',return_value=(rgb,dict(status='unavailable',models=[]))):
            out,e=A.apply(rgb,points,'balanced')
        self.assertEqual(e['status'],'partial')
        self.assertGreater(float(out.mean()),float(rgb.mean()))
        self.assertEqual(e['decisions']['exposure_ev'],.5)
        self.assertIn('model unavailable; scene exposure retained',e['message'])
        self.assertEqual(e['stages'][0]['status'],'unavailable')

    def test_missing_local_geometry_retains_explicit_scene_exposure(self):
        rgb,points=fixture((100,80,60))
        for invalid in (None,points[:100],points*np.nan,np.zeros((478,2))):
            with patch.object(A,'lighting_prediction') as worker:
                out,e=A.apply(rgb,invalid,'balanced')
            worker.assert_not_called()
            self.assertEqual(e['status'],'partial')
            self.assertGreater(float(out.mean()),float(rgb.mean()))
            self.assertEqual(e['requested_scene_exposure_ev'],.5)
            self.assertIn('analysis unavailable; scene exposure retained',e['message'])
            self.assertNotIn('analysis',e)

    def test_invalid_foreground_support_uses_honest_global_only_fallback(self):
        rgb,points=fixture((100,80,60))
        for mask in (np.zeros((10,10)),np.full(rgb.shape[:2],np.nan)):
            out,e=A.apply(rgb,points,'natural',mask)
            self.assertEqual(e['status'],'partial')
            self.assertGreater(float(out.mean()),float(rgb.mean()))
            np.testing.assert_array_equal(out[160,160],out[310,160])

    def test_all_clipped_input_keeps_pixels_and_reports_missing_local_support(self):
        rgb,points=fixture((255,255,255))
        with patch.object(A,'lighting_prediction') as worker:
            out,e=A.apply(rgb,points,'recovery')
        worker.assert_not_called()
        np.testing.assert_array_equal(out,rgb)
        self.assertEqual(e['status'],'partial')
        self.assertEqual(e['changed_pixels'],0)
        self.assertEqual(e['requested_scene_exposure_ev'],.75)
        self.assertEqual(e['applied_gain_ev_p10_p50_p90'],[0.,0.,0.])

    def test_lighting_prediction_is_cached_once_with_independent_metadata(self):
        rgb,points=self.subtle_portrait();A._lighting_cache=None
        try:
            model=dict(status='applied',models=[dict(engine='retinex',model_sha256='synthetic')])
            with patch.object(E,'apply',return_value=(rgb,model)) as worker:
                for key in A.PROFILES:
                    _,e=A.apply(rgb,points,key)
                    self.assertEqual(e['stages'][0]['cache_hit'],key!='natural')
                self.assertEqual(worker.call_count,1)
                _,first=A.lighting_prediction(rgb)
                first['models'][0]['model_sha256']='mutated'
                _,second=A.lighting_prediction(rgb)
                self.assertEqual(second['models'][0]['model_sha256'],'synthetic')
        finally:A._lighting_cache=None

    def test_failed_predictions_are_not_cached(self):
        rgb,_=self.subtle_portrait();A._lighting_cache=None
        try:
            with patch.object(E,'apply',return_value=(rgb,dict(status='unavailable',models=[]))) as worker:
                A.lighting_prediction(rgb);A.lighting_prediction(rgb)
                self.assertEqual(worker.call_count,2)
                self.assertIsNone(A._lighting_cache)
        finally:A._lighting_cache=None

    def test_lighting_field_fills_feature_holes_and_ignores_unmeasured_pixels(self):
        ev=np.broadcast_to(np.linspace(-.2,.8,200,dtype=np.float32),(180,200)).copy()
        weight=np.zeros_like(ev);weight[25:145,30:75]=1;weight[25:145,125:170]=1
        valid=weight>.2
        field=A._lighting_field(ev,weight,valid,8)
        alternate=ev.copy();alternate[~valid]=20
        np.testing.assert_allclose(field,A._lighting_field(alternate,weight,valid,8),atol=1e-6)
        self.assertTrue(np.isfinite(field).all())
        self.assertLess(np.abs(np.diff(field[80,60:140])).max(),.05)
        constant=A._lighting_field(np.full_like(ev,.65),weight,valid,8)
        np.testing.assert_allclose(constant,.65,atol=1e-6)

    def test_face_feather_is_smooth_and_zero_outside(self):
        width=200*A.FACE_FEATHER_WIDTH
        distance=np.linspace(-2,width+2,441,dtype=np.float32)
        alpha=A._face_feather(distance,200)
        self.assertTrue((np.diff(alpha)>=0).all())
        self.assertTrue((alpha[distance<=0]==0).all())
        self.assertTrue((alpha[distance>=width]==1).all())

    def test_source_arrays_are_not_mutated(self):
        rgb,points=self.subtle_portrait();mask=np.ones(rgb.shape[:2],np.float32)
        originals=[x.copy() for x in (rgb,points,mask)]
        with patch.object(A,'lighting_prediction',return_value=(rgb.copy(),dict(status='applied',models=[]))):
            A.apply(rgb,points,'balanced',mask)
        for actual,original in zip((rgb,points,mask),originals):
            np.testing.assert_array_equal(actual,original)

    def test_unknown_profile_is_not_silently_selected(self):
        rgb,points=fixture()
        with self.assertRaises(ValueError):A.apply(rgb,points,'unknown')
        with self.assertRaises(ValueError):E.validate({'adaptive_profile':'invented'})

    def test_staff_form_routes_lighting_and_ignores_old_fixed_stack(self):
        with patch.object(main.background,'choices',return_value=[{'key':'hr','installed':True}]):
            options=main._opts({'opts':'1','adaptive_profile':'balanced','enhancer_skin':'100',
                'enhancer_lighting':'80','auto_adjust':'on','fix_shadows':'on','exposure':'1.5'})
        self.assertEqual(options['enhancement_options']['adaptive_profile'],'balanced')
        self.assertEqual(options['enhancement_options']['skin'],0)
        self.assertFalse(options['auto_adjust']);self.assertFalse(options['fix_shadows'])
        self.assertFalse(any(options['adjustments'].values()))
        self.assertEqual(options['background_engine'],'hr')

    def test_full_frame_processing_calls_lighting_once_without_legacy_stack(self):
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
        self.assertEqual(result.measurements['adaptive_quality']['mode'],'lighting_only')
        self.assertIn('image_sha256',result.measurements['final_highlights'])
        self.assertFalse(result.ok)


if __name__=='__main__':unittest.main()
