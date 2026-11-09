import tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from internet_archive import InternetArchive,hashes
from experiments import save,load
from test_internet_archive import FakeAPI
SID='20261109T055133Z-704e15'

class ManualArchiveTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.data=self.root/'ssd/sessions';self.folder=self.data/SID;self.folder.mkdir(parents=True)
  self.m=dict(id=SID,capture_origin='manual',state='completed',started_epoch=1,stopped_epoch=10,video_playback=dict(state='completed',frame_count=3))
  save(self.folder/'manifest.json',self.m);(self.folder/'video.mp4').write_bytes(b'original video');(self.folder/'rf.jsonl').write_text('RF observations')
  station=SimpleNamespace(lock=threading.RLock(),exiting=threading.Event(),youtube=SimpleNamespace(busy=lambda sid:False))
  self.api=FakeAPI();self.a=InternetArchive(station,self.root/'app',self.data,lambda:dict(available=True),api=self.api,start=False)
  self.a.config['manual_uploads_enabled']=True;self.a.discover();self.job=self.a.job_cache[SID]
 def test_manual_recording_uploads_without_invented_anomalous_review(self):
  self.assertTrue(self.job['manual_scope']);self.assertTrue(self.a.current_review(self.job))
  self.assertNotIn('anomalous',self.job['custom_tags']);self.assertIn('manual-recording',self.job['custom_tags'])
  self.assertFalse((self.folder/'archive-decision.json').exists())
  self.assertEqual({x['name'] for x in self.job['files']},{'video.mp4','rf.jsonl','session.json','archive-index.json'})
  with patch('internet_archive.PART_SIZE',4):
   for _ in range(30):
    if self.job['state']=='verifying':break
    self.a.send(self.job)
  self.assertEqual(self.job['state'],'verifying')
  self.assertTrue(self.a.verify(self.job));self.assertEqual(self.job['state'],'retaining')
  self.a.cleanup(self.job);self.assertTrue((self.folder/'video.mp4').exists())
 def test_updated_annotations_keep_item_and_reuse_verified_original(self):
  self.job['verified_at']=time.time();self.job['state']='retaining';identifier=self.job['identifier']
  rev='a'*64;pair={}
  for kind in ('original','annotated'):
   name='reviewed-'+rev+'/frame-000000001-'+kind+'.png';p=self.folder/'frames'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(kind.encode());pair[kind]=dict(file=name,sha256=hashes(p)['sha256'])
  save(self.folder/'frames/reviewed-index.json',dict(review_revision=rev,frames=[pair]))
  save(self.folder/'review-annotations.json',dict(annotations=[dict(label='not_anomalous',bounds=[1,2,3,4])]))
  save(self.folder/'archive-decision.json',dict(export_version=3,bundle_ready=True,confirmed_anomalous=False,review_revision=rev,reviewed_epoch=20))
  (self.folder/'video-annotated.mp4').write_bytes(b'annotated video')
  self.assertFalse(self.a.current_review(self.job))
  self.a.complete_session_plan(self.job,self.m)
  self.assertEqual(self.job['identifier'],identifier);self.assertEqual(self.job['manual_revision'],rev)
  self.assertIn('video.mp4',self.job['reuse_verified_files']);self.assertIn('video-annotated.mp4',{e['name'] for e in self.job['files']})
  self.assertEqual(len([e for e in self.job['files'] if e['name'].startswith('frames/')]),3)
 def test_manual_transfer_precedes_automatic_job(self):
  other=dict(self.job,id='automatic',manual_scope=False,manual_priority_epoch=time.time()+1000,last_step=0)
  self.a.job_cache['automatic']=other;self.a.next_discovery=time.time()+1000
  with patch.object(self.a,'send') as send,patch.object(self.a,'publish'),patch.object(self.a,'sync_tags'):
   self.a.tick();self.assertEqual(send.call_args.args[0]['id'],SID)
 def test_changed_source_cannot_reuse_prepared_checksum(self):
  (self.folder/'video.mp4').write_bytes(b'changed! video')
  with self.assertRaisesRegex(ValueError,'changed'):self.a.send(self.job)
 def test_old_manual_recordings_are_not_republished_by_new_policy(self):
  self.a.config['manual_uploads_since_epoch']=100
  self.assertFalse(self.a.archive_eligible(SID))
 def test_negative_object_corrections_do_not_withdraw_manual_publication(self):
  import archive_withdrawal
  path=self.data.parent/'uap-lab/email-reviews/training-manifest.json';path.parent.mkdir(parents=True);save(path,{'examples':[]})
  with patch.object(archive_withdrawal,'correction') as correction:
   archive_withdrawal.reconcile(self.a);correction.assert_not_called()
 def test_disabled_manual_policy_does_not_publish_unreviewed_capture(self):
  self.a.config['manual_uploads_enabled']=False
  self.assertFalse(self.a.archive_eligible(SID))
if __name__=='__main__':unittest.main()
