import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
from evaluate_candidate import gate
from model_transition import transition
from controller import Controller,save

class SafetyTests(unittest.TestCase):
 def test_gate_rejects_regression_and_disabled_anomaly(self):
  base=dict(total=20,export_max_absolute_error=0,per_class={'anomalous':dict(tp=8,fp=1),'cloud':dict(tp=10,fp=0)},thresholds={'anomalous':.8})
  self.assertTrue(gate(base,base,list(base['per_class']),list(base['per_class']))['passed'])
  for label,key,value in [('anomalous','tp',7),('cloud','fp',1)]:
   candidate=copy.deepcopy(base);candidate['per_class'][label][key]=value
   self.assertFalse(gate(candidate,base,list(base['per_class']),list(base['per_class']))['passed'])
  candidate=copy.deepcopy(base);candidate['thresholds']['anomalous']=1.1
  self.assertFalse(gate(candidate,base,list(base['per_class']),list(base['per_class']))['passed'])
 def test_transition_preserves_coverage_and_rejects_tampering(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'evaluation.json';p.write_text(json.dumps(dict(passed=True,baseline_version='old',candidate_version='new')))
   config={'model_transition':dict(from_version='old',to_version='new',evaluation_path=str(p),evaluation_sha256=hashlib.sha256(p.read_bytes()).hexdigest())}
   state=dict(model='old',generation='recording',last_sequence=900,offset=123,tracks={'object':1})
   updated=transition(state,{'version':'new'},config)
   for key in ('generation','last_sequence','offset','tracks'):self.assertEqual(updated[key],state[key])
   self.assertEqual(state['model'],'old');self.assertEqual(updated['model'],'new')
   p.write_text('{}')
   with self.assertRaises(ValueError):transition(state,{'version':'new'},config)
   with self.assertRaises(ValueError):transition(state,{'version':'new'},{})
 def test_completed_fingerprint_does_not_retrain(self):
  with tempfile.TemporaryDirectory() as t:
   save(Path(t)/'status.json',dict(completed_fingerprint='a'*64,phase='rejected'))
   c=Controller(dict(root=t,remote_app='/app',remote_python='python',host='station'))
   c.state['completed_recipe']=c.recipe;c.snapshot=Mock(return_value={'fingerprint':'a'*64});c.download=Mock();c.tick();c.download.assert_not_called()
 def test_interrupted_activation_rolls_back_before_more_work(self):
  with tempfile.TemporaryDirectory() as t:
   c=Controller(dict(root=t,remote_app='/app',remote_python='python',host='station'))
   c.state=dict(phase='activating',remote_candidate='/candidate',fingerprint='a'*64);c.rpc=Mock();c.recover()
   c.rpc.assert_called_once_with('deploy.py','rollback','--folder','/candidate');self.assertEqual(c.state['phase'],'rolled_back')
if __name__=='__main__':unittest.main()

class ReleaseQueueTests(unittest.TestCase):
 def test_pending_notice_survives_connection_failure_and_retries(self):
  with tempfile.TemporaryDirectory() as t:
   c=Controller(dict(root=t,remote_app='/app',remote_python='python',host='station'))
   c.mark('deployed',remote_candidate='/candidate',pending_release=dict(version='new'))
   c.rpc=Mock(side_effect=OSError('offline'))
   with self.assertRaises(OSError):c.notify_release()
   self.assertEqual(json.loads((Path(t)/'status.json').read_text())['pending_release']['version'],'new')
   c.rpc=Mock(return_value={'queued':True,'complete':True});c.notify_release();c.notify_release();self.assertEqual(c.rpc.call_count,2);self.assertIsNone(c.state['pending_release'])
 def test_unreleased_candidate_has_no_notice(self):
  with tempfile.TemporaryDirectory() as t:
   c=Controller(dict(root=t,remote_app='/app',remote_python='python',host='station'));c.state={'phase':'rejected'};c.rpc=Mock();c.notify_release();c.rpc.assert_not_called()

 def test_cleanup_failure_keeps_release_pending_for_retry(self):
  with tempfile.TemporaryDirectory() as t:
   c=Controller(dict(root=t,remote_app='/app',remote_python='python',host='station'));c.state=dict(phase='deployed',remote_candidate='/candidate',pending_release={'version':'new'})
   c.rpc=Mock(side_effect=[{'queued':True},OSError('cleanup interrupted')])
   with self.assertRaises(OSError):c.notify_release()
   self.assertEqual(c.state['pending_release']['version'],'new')
   c.rpc.assert_called_with('provisional_station.py','--release','new')
