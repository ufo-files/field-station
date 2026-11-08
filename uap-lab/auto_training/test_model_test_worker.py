import unittest
from model_test_worker import score
class ScoringTests(unittest.TestCase):
 def test_saved_threshold_and_binary_rule(self):
  rows=[dict(origin=str(i),group='recording',label=label,native_width=16,native_height=16) for i,label in enumerate(['anomalous','not_anomalous'])]
  policy=dict(thresholds={'anomalous':.8})
  result=score(rows,[{'scores':{'anomalous':.9}},{'scores':{'anomalous':.7}}],policy)
  self.assertEqual(result['correct'],2);self.assertEqual(result['accuracy'],1);self.assertEqual(policy['thresholds']['anomalous'],.8)
 def test_inference_errors_are_not_negative_predictions(self):
  row=dict(origin='x',group='g',label='not_anomalous',native_width=16,native_height=16)
  for results in ([],[{'error':'failed'}],[{'scores':{'anomalous':float('nan')}}]):
   with self.assertRaises(ValueError):score([row],results,dict(thresholds={'anomalous':.8}))
