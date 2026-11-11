import unittest
from training_policy import machine_benchmark_training
class MachineBenchmarkTrainingTests(unittest.TestCase):
 def dataset(self):
  return dict(training_lane='machine_only',evaluation_mode='shared_human_benchmark',shadow_only=True,fixed_anomaly_threshold=.8,samples=[dict(label=label,label_source='machine',human_confirmed=False,split='train') for label in ['anomalous','not_anomalous']])
 def test_single_recording_machine_rows_can_train(self):self.assertTrue(machine_benchmark_training(self.dataset()))
 def test_human_labels_cannot_enter_machine_training(self):
  d=self.dataset();d['samples'][0]['human_confirmed']=True
  with self.assertRaises(ValueError):machine_benchmark_training(d)
 def test_no_bypass_for_human_training(self):
  d=self.dataset();d['training_lane']='human';self.assertFalse(machine_benchmark_training(d))
 def test_cannot_change_threshold_or_go_live(self):
  for key,value in [('fixed_anomaly_threshold',.1),('shadow_only',False)]:
   d=self.dataset();d[key]=value
   with self.assertRaises(ValueError):machine_benchmark_training(d)
 def test_both_classes_required(self):
  d=self.dataset();d['samples']=d['samples'][:1]
  with self.assertRaises(ValueError):machine_benchmark_training(d)
