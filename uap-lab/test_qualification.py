import unittest
from qualification import issues,interval_sample
class QualificationTests(unittest.TestCase):
 def sample(self):return dict(native=dict(analyzed_epoch=100,latency_seconds=1,generation_missing_frames=0,capture=dict(captured_frames=600,measured_fps=59.94)),rf=dict(receivers={k:dict(timestamp=100) for k in ['narrow','wide']}))
 def test_good_metrics_have_no_faults(self):self.assertEqual(issues(self.sample(),101),[])
 def test_missing_frames_or_stale_rf_cannot_pass(self):
  sample=self.sample();sample['native']['generation_missing_frames']=1;sample['rf']['receivers']['wide']['timestamp']=0;faults=issues(sample,101);self.assertIn('missing_analysis_frames',faults);self.assertIn('wide_rf_stale',faults)
 def test_latency_is_fault_even_when_spool_preserves_evidence(self):
  sample=self.sample();sample['native']['latency_seconds']=10;self.assertIn('analysis_latency_over_5_seconds',issues(sample,101))

 def test_old_failures_remain_in_source_but_new_interval_can_qualify(self):
  sample=self.sample();sample['native'].update(generation='run-a',generation_missing_frames=5);sample['native']['capture'].update(timestamp_gap_count=3,captured_frames=1200,last_pts_seconds=20)
  old=dict(generation='run-a',generation_missing_frames=5,capture=dict(timestamp_gap_count=3,captured_frames=600,last_pts_seconds=10))
  interval=interval_sample(sample,old);self.assertEqual(issues(interval,101),[]);self.assertEqual(sample['native']['capture']['timestamp_gap_count'],3)
  sample['native']['capture']['timestamp_gap_count']=4;self.assertIn('capture_timestamp_gap_count',issues(interval_sample(sample,old),101))
