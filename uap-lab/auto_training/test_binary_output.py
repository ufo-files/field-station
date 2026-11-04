import math,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'recognition')]
from binary_decision import decide
from classification_policy import apply_results
from training_policy import evaluate
class BinaryOutputTests(unittest.TestCase):
 def test_boundary_low_confidence_and_negative_threshold(self):
  for anomaly,expected in [(.97,'anomalous'),(.969,'not_anomalous'),(.5,'not_anomalous'),(.01,'not_anomalous')]:
   self.assertEqual(decide({'anomalous':anomaly,'not_anomalous':1-anomaly},.97),expected)
 def test_errors_are_not_silently_negative(self):
  for scores in ({},{'anomalous':.1},{'anomalous':math.nan,'not_anomalous':.5}):
   with self.assertRaises(ValueError):decide(scores,.97)
  with self.assertRaises(ValueError):apply_results([dict(box=[0,0,10,10])],[0],[{'error':'failed'}],dict(version='v',classes=['anomalous','not_anomalous'],minimum_native_size=8,thresholds={'anomalous':.97}))
 def test_runtime_and_evaluation_have_identical_binary_results(self):
  scores=[{'anomalous':.99,'not_anomalous':.01},{'anomalous':.6,'not_anomalous':.4},{'anomalous':.01,'not_anomalous':.99}]
  policy=dict(version='v',classes=['anomalous','not_anomalous'],minimum_native_size=8,thresholds={'anomalous':.97,'not_anomalous':1.1})
  observations=[dict(box=[0,0,10,10]) for _ in scores]+[dict(box=[0,0,3,3])]
  apply_results(observations,[0,1,2],[dict(scores=s) for s in scores],policy)
  rows=[dict(origin=str(i),group='g',label='not_anomalous',native_width=10 if i<3 else 3,native_height=10 if i<3 else 3) for i in range(4)]
  probabilities=[[s[c] for c in policy['classes']] for s in scores]+[[.999,.001]]
  report=evaluate(rows,probabilities,policy['classes'],policy['thresholds'])
  self.assertEqual([p['label'] for p in report['predictions']],[o['suggested_label'] for o in observations])
  self.assertEqual(report['unknown'],0)
  self.assertEqual(observations[-1]['classification_status'],'below_model_minimum_size')
