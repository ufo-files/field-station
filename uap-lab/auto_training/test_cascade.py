import json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from cascade import ranked_order,run_manual,pending
class CascadeTests(unittest.TestCase):
 def test_stable_first_and_followers_ranked_on_same_point(self):
  history={'points':[{'lanes':{'human':{'accuracy':.5,'false_positive_rate':.5},'experimental':{'accuracy':.7,'false_positive_rate':.2},'hybrid':{'accuracy':.9,'false_positive_rate':.1},'machine':{'accuracy':.8,'false_positive_rate':.3}}}]}
  self.assertEqual(ranked_order(history,'accuracy'),['human','hybrid','machine','experimental'])
  self.assertEqual(ranked_order(history,'false_positive_rate'),['human','hybrid','experimental','machine'])
  self.assertEqual(ranked_order({},'accuracy'),['human','experimental','hybrid','machine'])
 def setup_controller(self,root):
  cfg=dict(enabled=True,runtime=str(root),comparison_root=str(root))
  c=types.SimpleNamespace(root=root,c={'cascade':cfg},state={'active_version':'stable','run_directory':str(root/'stable'),'phase':'deployed'},rpc=lambda *a,**k:None)
  return c
 def test_sequential_failure_continues_and_restart_does_not_retrain(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);c=self.setup_controller(root);calls=[]
   def tick():calls.append('human');c.state.update(manual_request_id='one',phase='deployed')
   c.tick=tick
   def train(cfg,cycle,lane):
    calls.append(lane)
    if lane=='hybrid':raise ValueError('training failed')
    return {'version':lane}
   module=types.SimpleNamespace(retry_publications=lambda *a:{},freeze_inputs=lambda *a:{'frozen':True},train_lane=train,compare=lambda *a:{'state':'complete'})
   with patch.dict('sys.modules',{'cascade_training':module,'worker':types.SimpleNamespace(model_folder=lambda *a:root/'stable')}):
    result=run_manual(c,{'id':'one'});self.assertEqual(calls,['human','experimental','hybrid','machine']);self.assertEqual(result['phase'],'complete_with_errors');self.assertFalse(pending(c,'one'))
    run_manual(c,{'id':'one'});self.assertEqual(len(calls),4)
 def test_pending_activation_waits_and_evaluation_retries_without_retraining(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);c=self.setup_controller(root);calls=[]
   def tick():calls.append('human');c.state.update(manual_request_id='two',phase='activation_pending',manual_activation_pending=True)
   c.tick=tick
   module=types.SimpleNamespace(retry_publications=lambda *a:{},freeze_inputs=lambda *a:{'frozen':True},train_lane=lambda cfg,cycle,lane:(calls.append(lane) or {'version':lane}),compare=lambda *a:(_ for _ in ()).throw(ValueError('offline')))
   with patch.dict('sys.modules',{'cascade_training':module,'worker':types.SimpleNamespace(model_folder=lambda *a:root/'stable')}):
    run_manual(c,{'id':'two'});self.assertEqual(calls,['human']);self.assertTrue(pending(c,'two'))
    c.state.update(phase='deployed',manual_activation_pending=False)
    result=run_manual(c,{'id':'two'});self.assertEqual(calls,['human','experimental','hybrid','machine']);self.assertEqual(result['phase'],'evaluation_retry_pending')
    module.compare=lambda *a:{'state':'complete'}
    result=run_manual(c,{'id':'two'});self.assertEqual(len(calls),4);self.assertEqual(result['phase'],'complete')
