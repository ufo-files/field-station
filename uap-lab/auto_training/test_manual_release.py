import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from manual_release import authorize
from model_transition import deployment_approved
from controller import Controller,save

class ManualReleaseTests(unittest.TestCase):
 def report(self):
  return dict(passed=False,improved=False,reasons=['held-out false positives increased'],candidate=dict(total=10,export_max_absolute_error=.001),baseline=dict(total=10))
 def test_manual_authorization_preserves_failed_validation(self):
  original=self.report();result=authorize(original,'request-1')
  self.assertFalse(result['passed']);self.assertFalse(result['improved']);self.assertEqual(result['reasons'],original['reasons'])
  self.assertTrue(deployment_approved(result));self.assertFalse(deployment_approved(original))
 def test_failed_exports_and_empty_evaluation_never_authorized(self):
  for value in (.1,float('nan'),float('inf'),None):
   r=self.report();r['candidate']['export_max_absolute_error']=value
   with self.assertRaises(ValueError):authorize(r,'request-1')
  r=self.report();r['candidate']['total']=0
  with self.assertRaises(ValueError):authorize(r,'request-1')
 def exercise(self,root,manual,calibration_rejected=False,reviews_valid=True):
  c=Controller(dict(root=str(root),remote_app='/app',remote_python='python',host='station'))
  if manual:c.manual_request_id=manual
  else:c.provisional_slot=1;c.c['provisional']={'start_epoch':0}
  fp='a'*64;c.snapshot=Mock(return_value=dict(fingerprint=fp,examples=10));c.remote=Mock();c.monitor=Mock();c.notify_release=Mock();c.reviews_still_valid=Mock(return_value=reviews_valid)
  save(root/'reviews'/fp/'reviews.json',dict(samples=[dict(label='not_anomalous')]))
  baseline=root/'incumbents'/'old';save(baseline/'candidate-policy.json',{});(baseline/'candidate-weights.pt').write_bytes(b'weights')
  c.rpc=Mock(return_value=dict(version='old',package='/old/candidate.mlpackage',policy='/old/candidate-policy.json',health={}))
  c.state.update(deployed_fingerprint=fp,deployed_recipe=c.recipe)
  def build(base,reviews,folder,ledger,progress=None):
   folder.mkdir(parents=True);return dict(fingerprint='data',classes=['anomalous','not_anomalous'],blockers=[])
  def run(script,args,folder):
   if script=='train_candidate.py':
    save(folder/'candidate-policy.json',{});(folder/'candidate.mlpackage').mkdir();(folder/'candidate-weights.pt').write_bytes(b'new');save(folder/'runtime-probe.json',[])
   if script=='refine_candidate.py' and calibration_rejected:
    import subprocess
    save(folder/'refinement-decision.json',dict(state='not_promoted',reason='No supported corrections'))
    raise subprocess.CalledProcessError(1,['refine'])
   if script=='evaluate_candidate.py':save(folder/'promotion-evaluation.json',self.report())
  c.run_script=Mock(side_effect=run)
  with patch('controller.build',side_effect=build):c.tick()
  return c
 def test_manual_deploys_even_when_unchanged_or_regressed_hourly_does_not(self):
  with tempfile.TemporaryDirectory() as t:
   c=self.exercise(Path(t)/'manual','request-1')
   self.assertEqual(c.state['phase'],'deployed');c.monitor.assert_called_once()
   self.assertNotIn('refine_candidate.py',[call.args[0] for call in c.run_script.call_args_list])
   first=c.state['active_version']
   c2=self.exercise(Path(t)/'manual2','request-2');self.assertNotEqual(first,c2.state['active_version'])
   hourly=self.exercise(Path(t)/'hourly',None)
   self.assertEqual(hourly.state['phase'],'rejected');hourly.monitor.assert_not_called()
   self.assertIn('refine_candidate.py',[call.args[0] for call in hourly.run_script.call_args_list])

 def test_calibration_rejection_still_finishes_comparison(self):
  with tempfile.TemporaryDirectory() as t:
   c=self.exercise(Path(t)/'run',None,True)
   self.assertEqual(c.state['phase'],'not_promoted')
   self.assertIn('evaluate_candidate.py',[call.args[0] for call in c.run_script.call_args_list])
   self.assertTrue((c.run_folder/'promotion-evaluation.json').is_file())
   c.monitor.assert_not_called()

 def test_manual_releases_frozen_snapshot_despite_new_or_corrected_reviews(self):
  with tempfile.TemporaryDirectory() as t:
   c=self.exercise(Path(t)/'manual','request-changing-reviews',reviews_valid=False)
   self.assertEqual(c.state['phase'],'deployed')
   c.monitor.assert_called_once()
   c.reviews_still_valid.assert_not_called()
   hourly=self.exercise(Path(t)/'hourly',None,reviews_valid=False)
   self.assertEqual(hourly.state['phase'],'superseded')
   hourly.monitor.assert_not_called()
