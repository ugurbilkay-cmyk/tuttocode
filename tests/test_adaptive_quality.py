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
    def subtle_portrait(self):
        rgb,points=fixture((200,170,150))
        rgb=np.rint(rgb*np.linspace(.80,1.10,rgb.shape[1])[None,:,None]).astype(np.uint8)
        rgb[:25]=235
        return rgb,points

    def test_clean_uniform_complexions_with_bright_background_are_exact_no_ops(self):
        for colour in ((65,45,35),(165,130,110),(230,210,190)):
            rgb,points=fixture(colour);rgb[:25]=235
            for profile in A.PROFILES:
                with patch.object(E,'apply') as worker:
                    out,e=A.apply(rgb,points,profile)
                    worker.assert_not_called()
                np.testing.assert_array_equal(out,rgb)
                self.assertEqual(e['status'],'unchanged')
                self.assertEqual(e['changed_pixels'],0)
                self.assertIn('no facial correction selected',e['message'])
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

    def test_nonflat_face_is_assessed_below_old_scene_disparity_gate(self):
        rgb,points=self.subtle_portrait()
        proposal=A._render(A._linear(rgb)*2**.15)
        outputs=[]
        for profile in A.PROFILES:
            with patch.object(A,'lighting_prediction',return_value=(proposal,dict(status='applied',models=[]))) as adviser:
                out,e=A.apply(rgb,points,profile)
            adviser.assert_called_once()
            self.assertLess(e['analysis']['scene_p99_linear_luminance']/e['analysis']['face_p90_linear_luminance'],2.5)
            self.assertLess(e['analysis']['regional_illumination_spread_ev'],.35)
            self.assertEqual(e['decisions']['exposure_ev'],0)
            self.assertGreater(e['changed_pixels'],0)
            self.assertLessEqual(e['decisions']['maximum_learned_lighting_ev'],A.PROFILES[profile]['exposure_ev']+.0001)
            oval=A.hotspots._polygon_mask(rgb.shape[:2],points[A.hotspots.FACE_OVAL])
            np.testing.assert_array_equal(out[~oval],rgb[~oval])
            outputs.append(np.mean(out.astype(float)-rgb))
        # Even a weak eligible proposal responds to profile strength, rather
        # than yielding the same image under three different ceilings.
        self.assertLess(outputs[0],outputs[1])
        self.assertLess(outputs[1],outputs[2])

    def test_cached_lighting_provenance_cannot_absorb_later_cleanup_models(self):
        rgb,points=self.subtle_portrait()
        A._lighting_cache=None
        try:
            with patch.object(E,'apply',return_value=(rgb,dict(status='applied',models=[dict(engine='retinex',strength=1.)]))) as worker:
                _,first=A.lighting_prediction(rgb)
                first['models'][0]['strength']=.1
                first['models'].append(dict(engine='blemish'))
                _,second=A.lighting_prediction(rgb)
                self.assertEqual(second['models'],[dict(engine='retinex',strength=1.)])
                self.assertTrue(second['cache_hit'])
                self.assertEqual(worker.call_count,1)
        finally:A._lighting_cache=None

    def test_identity_and_darker_lighting_proposals_do_not_force_visible_edits(self):
        rgb,points=self.subtle_portrait()
        for proposal in (rgb,A._render(A._linear(rgb)*.75)):
            for profile in A.PROFILES:
                with patch.object(A,'lighting_prediction',return_value=(proposal,dict(status='applied',models=[]))):
                    out,e=A.apply(rgb,points,profile)
                np.testing.assert_array_equal(out,rgb)
                self.assertEqual(e['status'],'unchanged')
                self.assertTrue(e['decisions']['lighting_adviser_requested'])

    def test_lighting_field_fills_protected_feature_holes_without_bright_edges(self):
        ev=np.full((180,200),.65,np.float32)
        weight=np.zeros_like(ev);weight[20:60,60:140]=1;weight[90:130,35:80]=1;weight[90:130,120:165]=1
        valid=weight>.2
        field=A._lighting_field(ev,weight,valid,8)
        np.testing.assert_allclose(field,.65,atol=1e-6)
        # A feature without eligible cleanup pixels still receives continuous
        # illumination; missing support cannot punch a zero-gain hole in it.
        self.assertGreater(field[85,100],.64)
        self.assertTrue(np.isfinite(field).all())

    def test_wide_face_feather_is_smooth_monotonic_and_zero_outside(self):
        width=200*A.FACE_FEATHER_WIDTH
        distance=np.linspace(-2,width+2,441,dtype=np.float32)
        alpha=A._face_feather(distance,200)
        self.assertTrue((np.diff(alpha)>=0).all())
        self.assertTrue((alpha[distance<=0]==0).all())
        self.assertTrue((alpha[distance>=width]==1).all())
        self.assertLess(A._face_feather(np.array([.1],np.float32),200)[0],.001)

    def test_variable_field_ignores_unmeasured_model_pixels(self):
        ev=np.broadcast_to(np.linspace(-.2,.8,200,dtype=np.float32),(180,200)).copy()
        weight=np.zeros_like(ev);weight[25:145,30:75]=1;weight[25:145,125:170]=1
        valid=weight>.2
        field=A._lighting_field(ev,weight,valid,8)
        alternate=ev.copy();alternate[~valid]=20
        np.testing.assert_allclose(field,A._lighting_field(alternate,weight,valid,8),atol=1e-6)
        self.assertTrue(np.isfinite(field).all())
        self.assertGreaterEqual(field.min(),ev[valid].min()-1e-6)
        self.assertLessEqual(field.max(),ev[valid].max()+1e-6)
        self.assertLess(np.abs(np.diff(field[80,60:140])).max(),.05)

    def test_learned_lighting_retains_highlights_and_creates_no_new_clipping(self):
        rgb,points=self.subtle_portrait()
        rgb[85:95,155:165]=[250,240,220]
        rgb[100:110,155:165]=[249,240,220]
        proposal=np.full_like(rgb,245)
        for profile in A.PROFILES:
            with patch.object(A,'lighting_prediction',return_value=(proposal,dict(status='applied',models=[]))):
                out,e=A.apply(rgb,points,profile)
            self.assertGreater(e['changed_pixels'],0)
            np.testing.assert_array_equal(out[rgb.max(axis=2)>=250],rgb[rgb.max(axis=2)>=250])
            self.assertFalse(((out.max(axis=2)>=250)&(rgb.max(axis=2)<250)).any())

    def test_unavailable_lighting_is_incomplete_rather_than_a_successful_no_op(self):
        rgb,points=self.subtle_portrait()
        with patch.object(A,'lighting_prediction',return_value=(rgb,dict(status='unavailable',models=[]))):
            out,e=A.apply(rgb,points,'recovery')
        np.testing.assert_array_equal(out,rgb)
        self.assertEqual(e['status'],'partial')
        self.assertIn('preparation incomplete',e['message'])
        self.assertIn('lighting unavailable',e['message'])
        self.assertNotIn('no facial correction selected',e['message'])

    def test_low_noise_texture_selects_polish_then_local_cleaning(self):
        rgb,points=self.subtle_portrait()
        texture=4*np.sin(np.arange(rgb.shape[1])*np.pi/3)[None,:,None]
        rgb=np.clip(np.rint(rgb+texture),0,249).astype(np.uint8)
        calls=[]
        def polish(image,p,strength):
            calls.append('polish')
            result=image.copy();result[0,0]=[1,2,3]
            return result,dict(status='applied',models=[],edited_pixels=1)
        def clean(image,p,values,protected_mask=None):
            calls.append('clean')
            np.testing.assert_array_equal(image[0,0],[1,2,3])
            self.assertTrue(protected_mask.any())
            return image,dict(status='unchanged',models=[],edited_pixels=0,candidate_spots=0),{}
        with patch.object(A,'lighting_prediction',side_effect=lambda r:(r,dict(status='applied',models=[]))), \
             patch.object(A.skin_guided,'apply',side_effect=polish),patch.object(A.blemishes,'apply',side_effect=clean):
            out,e=A.apply(rgb,points,'balanced')
        self.assertEqual(e['decisions']['denoise_percent'],0)
        self.assertGreater(e['source_diagnosis']['texture_need'],0)
        self.assertGreater(e['decisions']['skin_percent'],0)
        self.assertGreater(e['decisions']['skin_cleaning_percent'],0)
        self.assertEqual(calls,['polish','clean'])
        phases=[s['phase'] for s in e['stages']]
        self.assertLess(phases.index('adaptive_highlights'),phases.index('adaptive_skin'))
        self.assertLess(phases.index('adaptive_skin'),phases.index('adaptive_skin_cleaning'))
        self.assertIn('feature_detail_guard',e)

    def test_missing_cleanup_support_does_not_destroy_valid_lighting_analysis(self):
        rgb,points=self.subtle_portrait()
        original=A.portrait_finish.analyse
        def unsupported(*args,**kwargs):
            diagnosis=original(*args,**kwargs)
            diagnosis['_cleanup_alpha'][:]=0
            diagnosis['report']['texture_need']=.5
            return diagnosis
        with patch.object(A.portrait_finish,'analyse',side_effect=unsupported), \
             patch.object(A,'lighting_prediction',side_effect=lambda r:(r,dict(status='applied',models=[]))):
            out,e=A.apply(rgb,points,'balanced')
        self.assertEqual(e['status'],'partial')
        self.assertIn('analysis',e)
        self.assertTrue(any(s['phase']=='adaptive_skin_cleanup' and s['status']=='unavailable' for s in e['stages']))
        self.assertEqual(e['decisions']['skin_percent'],0)

    def test_aggressive_cleanup_cannot_erase_feature_or_source_mark_detail(self):
        rgb,points=self.subtle_portrait()
        texture=5*np.sin(np.arange(rgb.shape[1])*np.pi/3)[None,:,None]
        rgb=np.clip(np.rint(rgb+texture),0,249).astype(np.uint8)
        rgb[83:87,133:137]=[45,28,20]
        diagnosis=A.portrait_finish.analyse(rgb,points)
        reference,_=A.portrait_finish.apply_highlights(rgb,diagnosis,A.PROFILES['balanced'])
        def polish(image,p,strength):
            return cv2.GaussianBlur(image,(0,0),4),dict(status='applied',models=[],edited_pixels=image.shape[0]*image.shape[1])
        def clean(image,p,values,protected_mask=None):
            painted=np.clip(image.astype(int)+10,0,249).astype(np.uint8)
            return painted,dict(status='applied',models=[],edited_pixels=painted.shape[0]*painted.shape[1],candidate_spots=1),{}
        with patch.object(A,'lighting_prediction',side_effect=lambda r:(r,dict(status='applied',models=[]))), \
             patch.object(A.skin_guided,'apply',side_effect=polish),patch.object(A.blemishes,'apply',side_effect=clean):
            out,e=A.apply(rgb,points,'balanced')
        protected=diagnosis['_feature_mask']|diagnosis['_mark_mask']
        np.testing.assert_array_equal(out[protected],reference[protected])
        self.assertGreater(e['decisions']['skin_percent'],0)
        self.assertIn(e['feature_detail_guard']['status'],('measured','unchanged'))
        if e['feature_detail_guard']['status']=='measured':
            self.assertGreaterEqual(e['feature_detail_guard']['minimum_final_projection'],.975)

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
