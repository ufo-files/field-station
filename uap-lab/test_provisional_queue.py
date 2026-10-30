import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import lab,provisional_queue as q
class QueueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);self.data=root/'lab';self.station=root/'station';(self.data/'runs').mkdir(parents=True);self.folder=self.station/'sessions/20261029T210000Z-abcdef';self.folder.mkdir(parents=True)
  self.patches=[patch.object(lab,'DATA',self.data),patch.object(lab,'STATION',self.station)];[p.start() for p in self.patches]
  lab.save(self.folder/'manifest.json',dict(state='completed'));(self.data/'runs'/('a'*32)).mkdir();self.job=dict(session_id=self.folder.name,created=time.time(),state='analyzing',run_id='a'*32,classification='unclassified',automatic_deletion=False);lab.save(self.folder/'provisional.json',self.job)
 def tearDown(self):
  [p.stop() for p in reversed(self.patches)];self.tmp.cleanup()
 def test_negative_is_retained_for_review_not_deleted(self):
  lab.save(self.data/'runs'/self.job['run_id']/'run.json',dict(state='complete',detected_frames=0,frame_count=100,processed_frames=100));q.tick();r=lab.read(self.data/'provisional-queue'/(self.folder.name+'.json'));self.assertEqual(r['state'],'review_required');self.assertEqual(r['classification'],'no_model_match');self.assertTrue(self.folder.exists());self.assertFalse(r['automatic_deletion'])
 def test_failure_never_becomes_negative(self):
  lab.save(self.data/'runs'/self.job['run_id']/'run.json',dict(state='failed',error='Offline'));q.tick();r=lab.read(self.data/'provisional-queue'/(self.folder.name+'.json'));self.assertEqual(r['state'],'analysis_failed');self.assertEqual(r['classification'],'unclassified')
 def test_restart_recovers_existing_dispatcher_without_new_run(self):
  lab.save(self.data/'runs'/self.job['run_id']/'run.json',dict(state='waiting_worker'))
  with patch.object(q,'recover_dispatcher') as recovery,patch.object(lab,'start_run') as start:q.tick();recovery.assert_called_once_with(self.job['run_id']);start.assert_not_called()
 def test_waiting_jobs_share_model_read_and_do_not_reimport_or_redispatch(self):
  model_id='b'*32;vid='c'*32;(self.data/'models'/model_id).mkdir(parents=True);lab.save(self.data/'models'/model_id/'model.json',dict(id=model_id,classes=['anomalous']))
  (self.data/'videos'/vid).mkdir(parents=True);lab.save(self.data/'videos'/vid/'video.json',dict(id=vid))
  for name in [self.folder.name,'20261029T210001Z-abcdef']:
   folder=self.station/'sessions'/name;folder.mkdir(exist_ok=True);lab.save(folder/'manifest.json',dict(state='completed'));lab.save(folder/'provisional.json',dict(session_id=name,created=time.time(),state='queued',video_id=vid,model_id=model_id))
  lab.save(self.data/'runs'/self.job['run_id']/'run.json',dict(id=self.job['run_id'],state='running',detached=True))
  with patch.dict('os.environ',{'UAP_LAB_WORKER_CONFIG':'test'}),patch('station_intake.import_session') as intake,patch.object(lab,'start_run') as start,patch.object(lab,'read',wraps=lab.read) as reads:
   q.tick();start.assert_not_called();intake.assert_not_called();self.assertEqual(sum(str(c.args[0]).endswith('/'+model_id+'/model.json') for c in reads.call_args_list),1)

 def test_complete_local_results_do_not_launch_duplicate_m6_run(self):
  model_id='b'*32;vid='c'*32;(self.data/'models'/model_id).mkdir(parents=True);lab.save(self.data/'models'/model_id/'model.json',dict(id=model_id))
  (self.data/'videos'/vid).mkdir(parents=True);lab.save(self.data/'videos'/vid/'video.json',dict(id=vid))
  lab.save(self.folder/'provisional.json',dict(session_id=self.folder.name,created=time.time(),state='queued',video_id=vid,model_id=model_id))
  with patch('recognition_queue.local_summary',return_value=dict(state='review_required',classification='local_model_suggestions',processed_frames=60,frame_count=60,automatic_deletion=False)),patch.object(lab,'start_run') as start:
   q.tick();start.assert_not_called()
  result=lab.read(self.data/'provisional-queue'/(self.folder.name+'.json'));self.assertEqual(result['processed_frames'],60);self.assertEqual(result['state'],'review_required');self.assertFalse(result['automatic_deletion'])
