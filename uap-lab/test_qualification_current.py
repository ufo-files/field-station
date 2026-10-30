import json,tempfile,unittest
from pathlib import Path
from qualification import measurement_sample,issues,interval_sample
class CurrentQualificationTests(unittest.TestCase):
 def test_current_capture_is_independent_of_delayed_journal(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'live').mkdir();(root/'capture').mkdir();(root/'capture/run-a').mkdir()
   (root/'live/native-analysis.json').write_text(json.dumps(dict(generation='run-a',analyzed_epoch=100,latency_seconds=20,capture={'last_frame_epoch':60})))
   (root/'capture/active.json').write_text(json.dumps({'generation':'run-a'}))
   (root/'capture/run-a/capture-health.json').write_text(json.dumps({'last_frame_epoch':100}));(root/'rf.json').write_text('{}')
   s=measurement_sample(root,root/'rf.json',root/'capture',101)
   self.assertEqual(s['native']['capture']['last_frame_epoch'],100);self.assertEqual(s['native']['latency_seconds'],20)
 def test_recognition_cannot_pass_on_motion_counts_alone(self):
  s={'native':{'analyzed_epoch':100,'latency_seconds':1},'rf':{'receivers':{k:{'timestamp':100} for k in ('narrow','wide')}},'recognition':{'updated_epoch':100,'frame_epoch':90,'integrity_ok':True}}
  self.assertIn('recognition_latency_over_5_seconds',issues(s,101))
  s['recognition'].update(frame_epoch=100,error='worker failed')
  self.assertIn('recognition_error',issues(s,101))
 def test_new_capture_generation_retains_new_counter_faults(self):
  s={'native':{'generation':'old-analysis','capture_generation':'new-camera','capture':{'timestamp_gap_count':1}}}
  previous={'generation':'old-analysis','capture_generation':'old-camera','capture':{'timestamp_gap_count':10}}
  self.assertEqual(interval_sample(s,previous)['native']['capture']['timestamp_gap_count'],1)
