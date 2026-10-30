import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab/recognition'))
from recognition_alerts import AlertOutbox
from mail_alerts import deliver,compose
class AlertTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.outbox=AlertOutbox(self.root)
  self.row=dict(sequence=1,pts_seconds=.1,received_epoch=100,observations=[dict(proposed_track_id='object-1',model='model',scores={'anomalous':.99},suggested_label='anomalous',box=[1,2,8,9])]);self.config=dict(sender='contact@example.org',recipient='owner@example.org');self.calls=[]
 def tearDown(self):self.tmp.cleanup()
 def queued(self):
  self.outbox.submit('run',self.row,[0],[b'PNG']);return next(self.root.glob('*/event.json')).parent
 def test_exact_crop_one_alert_per_track_across_restart(self):
  folder=self.queued();self.assertEqual((folder/'object.png').read_bytes(),b'PNG')
  self.assertEqual(AlertOutbox(self.root).submit('run',dict(self.row,sequence=2),[0],[b'other']),0)
  event=json.loads((folder/'event.json').read_text());self.assertFalse(event['human_confirmed']);self.assertEqual(event['bounds'],[1,2,8,9])
 def test_unknown_and_bird_never_notify(self):
  for label in ['unknown','bird','insect','airplane','cloud']:
   self.row['observations'][0]['suggested_label']=label;self.assertEqual(self.outbox.submit('run',self.row,[0],[b'PNG']),0)
 def test_send_once_exactly_one_attachment(self):
  folder=self.queued()
  for _ in range(2):deliver(folder,self.config,send=lambda *args:self.calls.append(args),check=lambda _:None)
  self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][2],folder/'object.png');self.assertIn('Human confirmation: no',self.calls[0][1])
 def test_uncertain_delivery_not_retried(self):
  folder=self.queued()
  def fail(*args):self.calls.append(args);raise TimeoutError('uncertain')
  self.assertEqual(deliver(folder,self.config,send=fail,check=lambda _:None)['state'],'uncertain')
  deliver(folder,self.config,send=fail,check=lambda _:None);self.assertEqual(len(self.calls),1)
 def test_missing_sender_does_not_attempt_send(self):
  folder=self.queued()
  def fail(_):raise RuntimeError('not configured')
  with self.assertRaises(RuntimeError):deliver(folder,self.config,send=lambda *args:self.calls.append(args),check=fail)
  self.assertEqual(self.calls,[]);self.assertFalse((folder/'delivery.json').exists())
 def test_restart_during_submission_is_not_resent(self):
  folder=self.queued();(folder/'delivery.json').write_text('{"state":"submitting"}')
  deliver(folder,self.config,send=lambda *args:self.calls.append(args));self.assertEqual(self.calls,[])
 def test_missing_screenshot_blocks_email(self):
  folder=self.queued();(folder/'object.png').unlink()
  with self.assertRaises(ValueError):deliver(folder,self.config,send=lambda *args:self.calls.append(args))
  self.assertEqual(self.calls,[])
 def test_activation_time_excludes_old_backlog(self):
  self.assertEqual(AlertOutbox(self.root,not_before=101).submit('run',self.row,[0],[b'PNG']),0)
  self.assertFalse(list(self.root.glob('*/event.json')))
 def test_mismatched_crops_are_rejected(self):
  with self.assertRaises(ValueError):self.outbox.submit('run',self.row,[0],[])
 def test_setup_message_is_labeled_test(self):
  folder=self.queued();event=json.loads((folder/'event.json').read_text());event['test']=True
  subject,body=compose(event);self.assertTrue(subject.startswith('TEST'));self.assertIn('not an anomalous detection',body);self.assertNotIn('was flagged by the station model',body)
if __name__=='__main__':unittest.main()
