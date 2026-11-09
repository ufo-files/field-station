import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from controller import Controller

class DeploymentHealthTests(unittest.TestCase):
 def exercise(self,health,baseline=100,manual=False):
  clock=[0.0]
  with tempfile.TemporaryDirectory() as tmp:
   c=Controller.__new__(Controller);c.run_folder=Path(tmp)
   if manual:c.manual_request_id='request'
   c.rpc=Mock(side_effect=lambda *a:{'health':{'updated_epoch':1000+clock[0],**health(clock[0])}})
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

 def test_manual_model_is_not_rejected_for_existing_capture_backlog(self):
  self.assertTrue(self.exercise(lambda t:self.row(t,latency=1000),manual=True)['passed'])
  with self.assertRaises(RuntimeError):self.exercise(lambda t:dict(self.row(t,latency=1000),error='decoder failed'),manual=True)

 def test_reports_slower_than_polling_still_confirm_advancing_model(self):
  def report(t):
   checkpoint=int(t//11)*11
   return dict(self.row(checkpoint,latency=12000),updated_epoch=1000+checkpoint)
  result=self.exercise(report,manual=True)
  self.assertTrue(result['passed'])
  self.assertTrue(any(s['progress_age_seconds'] and s['healthy'] for s in result['samples']))
  self.assertGreaterEqual(result['samples'][-1]['elapsed_seconds'],45)
 def test_twenty_second_checkpoints_pass_only_on_new_progress(self):
  def report(t):
   checkpoint=int(t//20)*20
   return dict(self.row(checkpoint),updated_epoch=1000+checkpoint)
  result=self.exercise(report,manual=True)
  self.assertTrue(result['passed'])
  self.assertGreater(result['samples'][-1]['health']['last_sequence'],result['samples'][-2]['health']['last_sequence'])
 def test_initial_progress_then_frozen_sequence_never_passes(self):
  with self.assertRaises(RuntimeError):self.exercise(lambda t:self.row(min(t,15)))
 def test_stale_reports_never_pass_even_when_sequence_advances(self):
  with self.assertRaises(RuntimeError):self.exercise(lambda t:dict(self.row(t),updated_epoch=900))
 def test_generation_change_restarts_stability_window(self):
  result=self.exercise(lambda t:dict(self.row(t),generation='run-a' if t<25 else 'run-b'))
  self.assertGreaterEqual(result['samples'][-1]['elapsed_seconds'],60)

class ManualActivationTests(unittest.TestCase):
 def controller(self):
  c=Controller.__new__(Controller)
  c.state=dict(phase='activating',manual_activation_pending=True,manual_request_id='request',run_directory='/unused',remote_candidate='/model',candidate_version='new')
  c.rpc=Mock(return_value={'health':{}});c.mark=Mock(side_effect=lambda phase,**fields:c.state.update(phase=phase,**fields));c.complete_activation=Mock();return c
 def test_failed_manual_activation_retries_same_model_without_rollback(self):
  c=self.controller();c.monitor=Mock(side_effect=RuntimeError('Decoder interrupted'))
  self.assertTrue(c.recover());self.assertEqual(c.state['phase'],'activation_pending');c.complete_activation.assert_not_called()
  self.assertFalse(any('rollback' in call.args for call in c.rpc.call_args_list))
  c.monitor=Mock();self.assertTrue(c.recover());c.complete_activation.assert_called_once()
  self.assertEqual(c.state['candidate_version'],'new')
 def test_interrupted_manual_activation_never_uses_automatic_recovery(self):
  c=self.controller();c.monitor=Mock();self.assertTrue(c.recover())
  c.rpc.assert_any_call('deploy.py','activate','--folder','/model');self.assertFalse(any('rollback' in call.args for call in c.rpc.call_args_list))
