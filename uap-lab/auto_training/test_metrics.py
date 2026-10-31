import json,tempfile,unittest
from pathlib import Path
from metrics import build
class MetricsTests(unittest.TestCase):
 def test_held_out_accuracy_unknowns_and_changed_cohorts(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for i in range(2):
    folder=root/'runs'/str(i);folder.mkdir(parents=True)
    metric=dict(total=10,unknown=3,per_class={'tree':dict(tp=7,fp=0,fn=3)},predictions=[dict(origin=str(i),truth='tree',group='g')])
    (folder/'promotion-evaluation.json').write_text(json.dumps(dict(epoch=i,passed=bool(i),candidate_version=str(i),baseline_version='old',candidate=metric,baseline=metric)))
   result=build(root);self.assertEqual(len(result['points']),2)
   self.assertEqual(result['points'][0]['candidate']['accuracy'],.7)
   self.assertNotEqual(result['points'][0]['cohort'],result['points'][1]['cohort'])
   self.assertNotIn('predictions',result['points'][0]['candidate'])
 def test_empty_history(self):
  with tempfile.TemporaryDirectory() as t:self.assertEqual(build(t)['points'],[])
