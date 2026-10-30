import unittest
from refine_candidate import select_cutoff
from training_policy import calibrate_against_incumbent
class CloudCorrectionTests(unittest.TestCase):
 def row(self,label,group):return dict(label=label,group=group,native_width=64,native_height=64)
 def test_threshold_comes_from_calibration_and_forbids_false_override(self):
  rows=[self.row('cloud','a'),self.row('cloud','b'),self.row('bird','c')]
  scores=[{'scores':{'cloud':.96,'bird':.04}},{'scores':{'cloud':.94,'bird':.06}},{'scores':{'cloud':.86,'bird':.14}}]
  chosen=select_cutoff(rows,scores,[{'label':'anomalous'}]*3)
  self.assertEqual(chosen['cutoff'],.93);self.assertEqual(chosen['false_overrides'],0);self.assertEqual(chosen['corrected_calibration_clouds'],2)
 def test_same_recording_does_not_supply_independent_evidence(self):
  rows=[self.row('cloud','same')]*8
  self.assertIsNone(select_cutoff(rows,[{'scores':{'cloud':.9999}}]*8,[{'label':'anomalous'}]*8))
 def test_wrong_correction_blocks_threshold(self):
  rows=[self.row('cloud','a'),self.row('cloud','b'),self.row('bird','c')]
  self.assertIsNone(select_cutoff(rows,[{'scores':{'cloud':1}}]*3,[{'label':'anomalous'}]*3))
 def test_baseline_budget_does_not_require_perfect_precision(self):
  rows=[self.row('cloud',str(i)) for i in range(6)]+[self.row('bird','other')]
  thresholds,evidence=calibrate_against_incumbent(rows,[[.95,.05]]*7,['cloud','bird'],{'per_class':{'cloud':{'fp':1},'bird':{'fp':0}}})
  self.assertEqual(thresholds['cloud'],.95);self.assertEqual(evidence['cloud']['false_positives'],1)
