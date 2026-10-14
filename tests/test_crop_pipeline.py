"""Real crop planning and honest stage states with synthetic anatomical points."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='crop-pipeline-'),OPENAI_API_KEY='',HMPO_KEY_URL='')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import processing as p,photomatic,pipeline_status,background,enhancement,measurements
from synthetic import Fake,make_face


class CropPipelineTests(unittest.TestCase):
    def setUp(self):
        self.data,self.analysis=make_face(W=3000,H=2000,scale=.9)
        self.profile=photomatic.country('united-kingdom-online-renewal')
        self.analyzer=Fake(self.analysis)

    def process(self,**options):
        return p.process(self.data,analyzer=self.analyzer,country_id=self.profile['id'],auto_adjust=False,fix_shadows=False,**options)

    def test_default_landscape_crop_fits_real_pixels_and_runs_background(self):
        evidence=dict(engine='hr',status='applied',label='Test matte',inference_seconds=0)
        with patch.object(background,'matte',return_value=(self.analysis.person_mask,evidence)) as matte:
            result=self.process(replace_bg=True,background_engine='hr')
        self.assertIsNotNone(result.jpeg)
        matte.assert_called_once()
        geometry=result.measurements['crop_geometry'];self.assertTrue(geometry['automatic_fit'])
        x,y,w,h=geometry['source_rect']
        self.assertGreater(geometry['requested_rect'][3],2000)
        self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
        self.assertLessEqual(x+w,3000);self.assertLessEqual(y+h,2000)
        self.assertAlmostEqual(w/h,5/7)
        self.assertFalse(any(c.key in ('framing','headsize','eyeposition') and c.status=='fail' for c in result.checks))
        self.assertEqual(result.measurements['face_analysis']['engine'],'Fake')

    def test_manual_crop_is_not_silently_replaced(self):
        with patch.object(background,'matte') as matte:
            result=self.process(replace_bg=True,crop={'zoom':.5,'x':0,'y':0})
        self.assertIsNone(result.jpeg);matte.assert_not_called()
        self.assertFalse(result.measurements['crop_geometry']['automatic_fit'])
        stages=pipeline_status.report({'replace_bg':True},result.measurements,result.as_dict()['checks'],False)
        self.assertEqual(next(s for s in stages if s['name']=='Background removal')['state'],'Skipped')

    def test_impossible_head_range_is_retained_after_feasible_output(self):
        self.data,self.analysis=make_face(W=3000,H=2000,scale=1.1);self.analyzer=Fake(self.analysis)
        result=self.process()
        self.assertIsNotNone(result.jpeg)
        self.assertTrue(any(c.key=='headsize' and c.status=='fail' for c in result.checks))
        self.assertFalse(result.ok)

    def test_crop_moves_inside_source_while_retaining_eye_bounds(self):
        points=self.analysis.faces[0].points
        rect=p._fit_auto_crop((-20,-100,1500,1900),(3000,2000),points,p._crown_y(points,self.analysis.person_mask),self.profile)
        self.assertIsNotNone(rect)
        x,y,w,h=rect;eye=(points[p.L_IRIS][1]+points[p.R_IRIS][1])/2
        self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
        self.assertTrue(24<=(eye-y)/h*100<=50)

    def test_no_fit_when_detected_head_is_clipped(self):
        points=self.analysis.faces[0].points
        self.assertIsNone(p._fit_auto_crop((0,0,1500,1900),(3000,2000),points,-30,self.profile))

    def test_framed_validation_never_automatically_recrops(self):
        result=self.process(framed=True)
        self.assertEqual(result.measurements['crop_geometry']['method'],'existing_frame')
        self.assertEqual(result.measurements['crop_geometry']['source_rect'],[0,0,3000,2000])

    def test_missing_face_runtime_is_visible_and_stages_not_claimed(self):
        with patch.object(self.analyzer,'analyze',side_effect=RuntimeError('private runtime detail')):
            result=self.process(replace_bg=True)
        self.assertIsNone(result.jpeg)
        self.assertEqual(result.measurements['face_analysis']['status'],'unavailable')
        self.assertNotIn('private runtime',str(result.checks))

    def test_no_completed_model_is_invented_from_selected_settings(self):
        rows=pipeline_status.report({'replace_bg':True,'enhancement_options':{'denoise':25,'skin':35,'detail':15}},
            {'local_enhancement':{'stages':[{'phase':'restore','status':'unavailable','models':[]}]}},[],True)
        by_name={r['name']:r for r in rows}
        for name in ('Background removal','NAFNet noise cleanup','Skin smoothing','Detail sharpening'):
            self.assertEqual(by_name[name]['state'],'Unavailable',name)

    def test_boundary_failure_does_not_turn_green_when_display_value_rounds(self):
        sections=measurements.report({'head_percent':44},[{'key':'headsize','status':'fail'}],self.profile)
        head=next(r for s in sections for r in s['rows'] if r['label']=='Head height')
        self.assertEqual(head['status'],'fail')


if __name__=='__main__':unittest.main(verbosity=2)
