import unittest
from collections import defaultdict
from recording_balance import sample_weights
from correction_experiment import select_rules,apply_rules
class BalanceTests(unittest.TestCase):
 def test_class_recording_and_duplicate_mass(self):
  rows=[dict(label='a',group='many',pixel_sha256=str(i)) for i in range(100)]+[dict(label='a',group='one',pixel_sha256='x')]*3+[dict(label='b',group='other',pixel_sha256='y')]
  weights=sample_weights(rows);mass=defaultdict(float)
  for r,w in zip(rows,weights):mass[(r['label'],r['group'])]+=w
  self.assertAlmostEqual(mass['a','many'],mass['a','one']);self.assertAlmostEqual(mass['a','many']+mass['a','one'],mass['b','other']);self.assertAlmostEqual(sum(weights),len(rows))
 def test_no_evidence_cannot_override_incumbent(self):
  b=[dict(origin='a',group='g',truth='anomalous',label='anomalous',raw_label='anomalous')];p=[dict(b[0],raw_label='not_anomalous',score=.999)]
  self.assertEqual(select_rules(b,p),[]);self.assertEqual(apply_rules(b,p,[])[0]['label'],'anomalous')
 def test_corrects_only_calibration_supported_region(self):
  b=[dict(origin=str(i),group=str(i//2),truth='not_anomalous',label='anomalous',raw_label='anomalous') for i in range(6)]
  p=[dict(r,raw_label='not_anomalous',score=.98) for r in b]
  rules=select_rules(b,p);self.assertEqual(rules[0]['cutoff'],.97)
  self.assertTrue(all(r['label']=='not_anomalous' for r in apply_rules(b,p,rules)))
  p[0]['score']=.9;self.assertEqual(apply_rules(b,p,rules)[0]['label'],'anomalous')
 def test_harm_rejects_region_and_identity_mismatch_rejected(self):
  b=[dict(origin=str(i),group=str(i),truth='not_anomalous' if i else 'anomalous',label='anomalous',raw_label='anomalous') for i in range(7)];p=[dict(r,raw_label='not_anomalous',score=.999) for r in b]
  self.assertEqual(select_rules(b,p),[])
  with self.assertRaises(ValueError):apply_rules(b,p[:-1],[])

class RecipeTests(unittest.TestCase):
 def test_weighting_change_requires_new_training_recipe(self):
  import tempfile
  from controller import Controller
  with tempfile.TemporaryDirectory() as root:
   cfg=dict(root=root,remote_app='/app',remote_python='python',host='station')
   self.assertNotEqual(Controller(cfg).recipe,Controller(dict(cfg,training_strategy='class_balanced')).recipe)
 def test_calibration_truth_mismatch_fails(self):
  old=[dict(origin='a',group='g',truth='anomalous',label='anomalous')]
  proposed=[dict(old[0],truth='not_anomalous',raw_label='not_anomalous',score=1)]
  with self.assertRaises(ValueError):select_rules(old,proposed)

class HybridWeightTests(unittest.TestCase):
 def test_machine_weight_cannot_drown_out_humans(self):
  human=[dict(label=c,group='h',pixel_sha256=c) for c in ['anomalous','not_anomalous']]
  pseudo=[dict(label='not_anomalous',group=str(i),pixel_sha256=str(i),pseudo_label=True) for i in range(100)]
  original=sample_weights(human);combined=sample_weights(human+pseudo)
  self.assertEqual(combined[:2],original)
  self.assertAlmostEqual(sum(combined[2:]),original[1]*.025)
