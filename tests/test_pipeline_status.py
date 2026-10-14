"""Saved execution outcomes for adaptive and legacy portrait preparation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='tuttocode-pipeline-status-'),
                  OPENAI_API_KEY='',HMPO_KEY_URL='',OFIQ_ENABLED='false')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import pipeline_status


class PipelineStatusTests(unittest.TestCase):
    def adaptive_rows(self, stages, decisions=None, **evidence):
        adaptive=dict(status='applied',decisions=decisions or {},stages=stages,**evidence)
        rows=pipeline_status.report({'enhancement_options':{'adaptive_profile':'balanced'}},
            {'adaptive_quality':adaptive},[],True)
        return {row['name']:row for row in rows}

    def test_adaptive_cleaning_uses_actual_decision_and_phase(self):
        rows=self.adaptive_rows([
            dict(phase='adaptive_skin_cleaning',status='applied',edited_pixels=17,
                 message='One permitted local spot repaired'),
        ],dict(skin_cleaning_percent=12))
        self.assertEqual(rows['Advanced skin cleaning']['state'],'Applied')
        self.assertIn('One permitted local spot',rows['Advanced skin cleaning']['detail'])

    def test_zero_pixel_stages_are_unchanged_despite_older_applied_status(self):
        rows=self.adaptive_rows([
            dict(phase='adaptive_skin_cleaning',status='applied',edited_pixels=0),
            dict(phase='adaptive_skin',status='applied',edited_pixels=0),
            dict(phase='adaptive_highlights',status='applied',edited_pixels=0),
        ],dict(skin_cleaning_percent=12,skin_percent=20),changed_pixels=0)
        for name in ('Advanced skin cleaning','Skin smoothing','Relative facial highlights',
                     'Automatic quality profile','Colour and lighting'):
            self.assertEqual(rows[name]['state'],'Unchanged',name)

    def test_failed_cleaning_remains_unavailable(self):
        rows=self.adaptive_rows([
            dict(phase='adaptive_skin_cleaning',status='unavailable',
                 message='Local cleaning could not finish'),
        ],dict(skin_cleaning_percent=12))
        self.assertEqual(rows['Advanced skin cleaning']['state'],'Unavailable')
        self.assertEqual(rows['Advanced skin cleaning']['detail'],'Local cleaning could not finish')

    def test_highlights_diagnosis_and_feature_check_use_recorded_outcomes(self):
        rows=self.adaptive_rows([
            dict(phase='adaptive_highlights',status='applied',edited_pixels=29,
                 message='Relative shine softened; clipped samples retained'),
        ],source_diagnosis=dict(status='measured',limitation='Appearance cues only.'),
          feature_detail_guard=dict(status='measured',minimum_final_projection=.99))
        self.assertEqual(rows['Relative facial highlights']['state'],'Applied')
        self.assertIn('clipped samples retained',rows['Relative facial highlights']['detail'])
        self.assertEqual(rows['Source photo diagnosis']['state'],'Completed')
        self.assertIn('Appearance cues only.',rows['Source photo diagnosis']['detail'])
        self.assertEqual(rows['Feature detail check']['state'],'Completed')
        self.assertIn('source reference',rows['Feature detail check']['detail'])

    def test_unchanged_and_unavailable_detail_checks_are_not_successful_edits(self):
        for status,state in [('unchanged','Unchanged'),('unavailable','Unavailable')]:
            rows=self.adaptive_rows([],feature_detail_guard=dict(status=status))
            self.assertEqual(rows['Feature detail check']['state'],state)

    def test_legacy_cleaning_and_absent_adaptive_evidence_keep_their_meaning(self):
        rows=pipeline_status.report({'enhancement_options':{'blemish':25}},
            {'skin_cleaning':dict(status='applied',edited_pixels=0,message='No local spot changed')},[],True)
        by_name={row['name']:row for row in rows}
        self.assertEqual(by_name['Advanced skin cleaning']['state'],'Unchanged')
        for name in ('Source photo diagnosis','Relative facial highlights','Feature detail check'):
            self.assertNotIn(name,by_name)
        rows=pipeline_status.report({'enhancement_options':{'skin':20}},
            {'local_enhancement':{'stages':[dict(phase='adaptive_skin',status='applied',edited_pixels=3)]}},[],True)
        self.assertEqual(next(r for r in rows if r['name']=='Skin smoothing')['state'],'Applied')

    def test_model_execution_with_zero_recorded_changes_is_unchanged(self):
        rows=pipeline_status.report({'enhancement_options':{'denoise':25}},
            {'local_enhancement':{'stages':[dict(phase='restore',status='applied',changed_pixels=0,
                models=[dict(engine='nafnet',model_sha256='test-model')])]}},[],True)
        self.assertEqual(next(r for r in rows if r['name']=='NAFNet noise cleanup')['state'],'Unchanged')


if __name__=='__main__':unittest.main()
