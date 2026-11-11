import unittest
from comparison import timeline
class ComparisonTests(unittest.TestCase):
 def row(self,**changes):
  return dict(dict(prospective=True,truth='not_anomalous',human='anomalous',hybrid='not_anomalous',generation='one',captured_epoch=1794410000,human_version='human1',hybrid_version='hybrid1'),**changes)
 def test_paired_daily_scores_and_exclusions(self):
  result=timeline([self.row(),self.row(prospective=False),self.row(truth=None),self.row(hybrid_version='human1')])
  self.assertEqual(len(result['points']),1)
  p=result['points'][0];self.assertEqual(p['count'],1)
  self.assertEqual(p['lanes']['human']['false_positive_rate'],1)
  self.assertEqual(p['lanes']['hybrid']['false_positive_rate'],0)
  self.assertIsNone(p['lanes']['human']['recall'])
 def test_model_changes_are_separate_comparisons(self):
  result=timeline([self.row(),self.row(hybrid_version='hybrid2')])
  self.assertEqual(len(result['points']),2)
