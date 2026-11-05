import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from controller import Controller

class DeploymentHealthTests(unittest.TestCase):
 def exercise(self,health,baseline=100):
  clock=[0.0]
  with tempfile.TemporaryDirectory() as tmp:
   c=Controller.__new__(Controller);c.run_folder=Path(tmp)
   c.rpc=Mock(side_effect=lambda *a:{'health':dict(health(clock[0]),updated_epoch=1000+clock[0])})
   with patch('controller.time.monotonic',side_effect=lambda:clock[0]),patch('controller.time.time',side_effect=lambda:1000+clock[0]),patch('controller.time.sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
    c.monitor('/unused','new',{'latency_seconds':baseline})
   return json.loads((c.run_folder/'deployment-health.json').read_text())
 def row(self,t,model='new',latency=0):return dict(model=model,generation='run-a',last_sequence=int(t*60),latency_seconds=latency,error=None)
 def test_restart_backlog_allowed_but_sustained_progress_required(self):
  result=self.exercise(lambda t:self.row(t,'old' if t<30 else 'new',125))
  self.assertTrue(result['passed']);self.assertEqual(result['restart_delay_seconds'],30)
  self.assertGreaterEqual(result['samples'][-1]['elapsed_seconds'],65)
 def test_zero_latency_is_healthy(self):self.assertTrue(self.exercise(lambda t:self.row(t),0)['passed'])
 def test_growing_lag_does_not_expand_allowance(self):
  with self.assertRaisesRegex(RuntimeError,'exceeds'):self.exercise(lambda t:self.row(t,latency=100+t*2))
 def test_frozen_sequence_and_wrong_model_never_pass(self):
  for f in [lambda t:dict(self.row(t),last_sequence=1),lambda t:self.row(t,'old')]:
   with self.assertRaises(RuntimeError):self.exercise(f)
 def test_error_never_passes(self):
  with self.assertRaises(RuntimeError):self.exercise(lambda t:dict(self.row(t),error='decoder failed'))

 def test_paused_capture_confirms_loaded_runtime_without_new_recordings(self):
  result=self.exercise(lambda t:dict(self.row(t),phase='capture_paused',runtime_ready=True,last_sequence=1,latency_seconds=9999))
  self.assertTrue(result['passed']);self.assertGreaterEqual(result['samples'][-1]['elapsed_seconds'],35)
 def test_paused_capture_cannot_confirm_old_or_unready_runtime(self):
  for fields in [dict(model='old',runtime_ready=True),dict(model='new',runtime_ready=False)]:
   with self.assertRaises(RuntimeError):self.exercise(lambda t:dict(self.row(t),phase='capture_paused',last_sequence=1,**fields))
