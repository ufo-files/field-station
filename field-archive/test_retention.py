import json,sqlite3,tempfile,time,unittest,sys
from pathlib import Path
from unittest.mock import patch
from retention import cycle,save
class RetentionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'uap-lab';self.audit=self.root/'audit';self.gen='run-abc';self.sid='20261030T000000Z-abcdef';self.session=self.root/'sessions'/self.sid;self.video=self.data/'videos'/('a'*32)
  self.session.mkdir(parents=True);self.video.mkdir(parents=True);(self.data/'recognition').mkdir()
  self.db=sqlite3.connect(self.data/'recognition/results.sqlite');self.db.execute('CREATE TABLE frames(generation,sequence,pts,epoch,model,observations)')
  for i in range(3):self.db.execute('INSERT INTO frames VALUES(?,?,?,?,?,?)',(self.gen,i,i+.1,0,'model',json.dumps([dict(suggested_label='bird',classification_status='inferred')])) )
  self.db.commit()
  save(self.session/'manifest.json',dict(capture_origin='provisional_motion',state='completed',spool_generation=self.gen,stopped_epoch=1))
  import os;os.utime(self.session/'manifest.json',(1,1))
  save(self.session/'buffer-state.json',dict(state='assembled',segments=[dict(start=0,end=3)]))
  save(self.root/'capture-spool'/self.gen/'recognition-ack.json',dict(generation=self.gen,integrity_ok=True,last_pts_seconds=10))
  (self.session/'buffer-segments').mkdir();(self.session/'buffer-segments/frame-times-000000000.jsonl').write_text(''.join(json.dumps(dict(sequence=i,pts_seconds=[.01,1,2.99][i]))+'\n' for i in range(3)))
  save(self.video/'video.json',dict(id=self.video.name,provenance=dict(session_id=self.sid)))
  for p in (self.session/'video.mkv',self.session/'video.mp4',self.video/'source',self.video/'preview.mp4'):p.write_bytes(b'footage')
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def run_cycle(self,apply=True):return cycle(self.root,self.audit,apply)
 def label(self,label,status='inferred'):
  self.db.execute('UPDATE frames SET observations=? WHERE sequence=1',(json.dumps([dict(suggested_label=label,classification_status=status)]),));self.db.commit()
 def test_fresh_station_waits_for_first_database(self):
  self.db.close();(self.data/'recognition/results.sqlite').unlink();r=self.run_cycle();self.assertEqual(r['phase'],'waiting_for_first_analysis');self.assertEqual(r['deleted_files'],0)
 def test_negative_dry_run_and_apply_preserve_metadata(self):
  self.assertEqual(self.run_cycle(False)['eligible'],1);self.assertTrue((self.video/'source').exists())
  r=self.run_cycle();self.assertEqual(r['deleted_files'],4);self.assertEqual(r['errors'],[]);self.assertFalse((self.video/'source').exists());self.assertTrue((self.video/'video.json').exists());self.assertEqual(self.run_cycle()['deleted_files'],0)
 def test_anomaly_and_unknown_retained(self):
  for label in ('anomalous','unknown'):
   self.label(label);self.assertEqual(self.run_cycle()['eligible'],0);self.assertTrue((self.video/'source').exists())
 def test_small_excluded_proposals_not_treated_as_classification_errors(self):
  self.label('unknown','below_model_minimum_size');self.assertEqual(self.run_cycle()['eligible'],1)
 def test_missing_analysis_retained(self):
  self.db.execute('DELETE FROM frames WHERE sequence=1');self.db.commit();self.assertEqual(self.run_cycle()['eligible'],0)
 def test_missing_timing_retained(self):
  (self.session/'buffer-segments/frame-times-000000000.jsonl').unlink();self.assertEqual(self.run_cycle()['eligible'],0)
 def test_training_source_and_crops_preserved(self):
  save(self.video/'annotations.json',[dict(label='bird')]);(self.video/'crop.png').write_bytes(b'training');self.assertEqual(self.run_cycle()['deleted_files'],2);self.assertTrue((self.video/'source').exists());self.assertTrue((self.video/'crop.png').exists())
 def test_manual_and_human_positive_retained(self):
  save(self.video/'annotations.json',[dict(label='anomalous')]);self.assertEqual(self.run_cycle()['eligible'],0)
  (self.video/'annotations.json').unlink();m=json.loads((self.session/'manifest.json').read_text());m['capture_origin']='manual';save(self.session/'manifest.json',m);self.assertEqual(self.run_cycle()['eligible'],0)
 def test_email_positive_overrides_negative(self):
  save(self.data/'email-reviews/examples'/('b'*32)/'review.json',dict(generation=self.gen,pts_seconds=1,label='anomalous'));self.assertEqual(self.run_cycle()['eligible'],0)
 def test_active_job_retained(self):
  save(self.data/'runs/job/run.json',dict(video_id=self.video.name,state='running'));self.assertEqual(self.run_cycle()['eligible'],0)
 def test_interrupted_deletion_resumes(self):
  original=Path.unlink;failed=[]
  def fail(p,*a,**k):
   if p.name=='video.mp4' and not failed:failed.append(True);raise OSError('simulated disk error')
   return original(p,*a,**k)
  with patch.object(Path,'unlink',fail):self.assertTrue(self.run_cycle()['errors'])
  r=self.run_cycle();self.assertFalse((self.video/'source').exists());self.assertEqual(r['errors'],[])
if __name__=='__main__':unittest.main()
