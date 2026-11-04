import hashlib,json,tempfile,unittest
from pathlib import Path
from review_retention import cycle
from retired_data import save
class RetentionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'uap-lab';self.data.mkdir();self.sessions=self.root/'sessions';self.sessions.mkdir();self.key='a'*32
  self.event=self.root/'notifications/outbox'/self.key;self.event.mkdir(parents=True)
  save(self.event/'event.json',dict(generation='run-abc',pts_seconds=5))
  (self.event/'source-frame.png').write_bytes(b'full');(self.event/'review.mp4').write_bytes(b'video')
  self.crop=self.data/'email-reviews/examples'/self.key/'native-object.png';self.crop.parent.mkdir(parents=True);self.crop.write_bytes(b'training')
  self.record=dict(event_id=self.key,sample_id=self.key,human_confirmed=True,label='not_anomalous',reviewed_epoch=1,generation='run-abc',pts_seconds=5,native_crop_sha256=hashlib.sha256(b'training').hexdigest())
  save(self.crop.parent/'review.json',self.record)
 def tearDown(self):self.tmp.cleanup()
 def test_negative_keeps_verified_training_and_removes_duplicate_media(self):
  r=cycle(self.data,self.sessions,{})
  self.assertEqual(r['deleted_files'],2);self.assertEqual(self.crop.read_bytes(),b'training');self.assertFalse((self.event/'review.mp4').exists())
  self.assertEqual(cycle(self.data,self.sessions,{})['deleted_files'],0)
 def test_anomalous_waits_for_verified_archive(self):
  save(self.crop.parent/'review.json',dict(self.record,label='anomalous'))
  self.assertEqual(cycle(self.data,self.sessions,{})['deleted_files'],0)
 def test_corrupt_training_copy_blocks_cleanup(self):
  self.crop.write_bytes(b'corrupt');r=cycle(self.data,self.sessions,{})
  self.assertEqual(r['deleted_files'],0);self.assertTrue(r['errors'])
 def test_active_event_and_dry_run_preserve_media(self):
  self.assertEqual(cycle(self.data,self.sessions,{},apply=False)['deleted_files'],2)
  self.assertTrue((self.event/'review.mp4').exists());self.assertFalse((self.event/'local-media-retired.json').exists())
  save(self.event.parent/'producer-state.json',dict(groups=[dict(id=self.key)]))
  self.assertEqual(cycle(self.data,self.sessions,{})['deleted_files'],0)
 def test_shared_segment_waits_for_last_pending_event(self):
  evidence=self.root/'notifications/evidence/run-abc/segment-000000001.mkv';evidence.parent.mkdir(parents=True);evidence.write_bytes(b'original')
  source=dict(generation='run-abc',segments=[dict(file=evidence.name)])
  save(self.event/'review-source.json',source)
  pending=self.event.parent/('b'*32);save(pending/'event.json',dict(generation='run-abc',pts_seconds=5));save(pending/'review-source.json',source)
  cycle(self.data,self.sessions,{});self.assertTrue(evidence.exists())
  save(pending/'label-queue-dismissed.json',dict(dismissed=True));cycle(self.data,self.sessions,{})
  self.assertFalse(evidence.exists())
 def test_verified_positive_cleanup_and_changed_review_guard(self):
  from archive_exports import digest
  positive=dict(self.record,label='anomalous');save(self.crop.parent/'review.json',positive)
  group=dict(kind='alert_web',id=self.key,source=str(self.event/'review.mp4'),reviewed_epoch=1,annotations=[positive]);sid='20261104T000000-abcdef';groups={sid:[group]};revision=digest([group]);folder=self.sessions/sid
  save(folder/'archive-decision.json',dict(review_revision=revision,bundle_ready=True))
  save(folder/'review-annotations.json',dict(review_revision=revision,annotations=[]))
  receipt=dict(state='cleaned',verified_at=1,files=[dict(name='review-annotations.json',sha256=hashlib.sha256((folder/'review-annotations.json').read_bytes()).hexdigest())])
  save(folder/'manifest.json',dict(internet_archive=receipt));(folder/'video-annotated.mp4').write_bytes(b'video')
  save(self.event/'review-clip.json',dict(state='ready',source_frames_verified=True,timeline=[]))
  r=cycle(self.data,self.sessions,groups)
  self.assertEqual(r['verified_sessions'],1);self.assertFalse((self.event/'review.mp4').exists());self.assertFalse((folder/'video-annotated.mp4').exists());self.assertTrue(self.crop.exists())
  marker=json.loads((self.event/'local-media-retired.json').read_text());self.assertEqual(marker['group'],group)
  (self.event/'review.mp4').write_bytes(b'new evidence')
  changed=dict(group,reviewed_epoch=2);r=cycle(self.data,self.sessions,{sid:[changed]})
  self.assertEqual(r['verified_sessions'],0);self.assertTrue((self.event/'review.mp4').exists())
 def test_private_copy_requires_retired_session_and_matching_receipt(self):
  from review_retention import prune_private
  archive=self.root/'overflow';unit=dict(session='session-one',files=[])
  key=hashlib.sha256(json.dumps(unit,sort_keys=True,separators=(',',':')).encode()).hexdigest();folder=archive/key
  save(folder/'manifest.json',unit);save(folder/'receipt.json',dict(verified=True,session='session-one',fingerprint=key));target=folder/'recording.tar';target.write_bytes(b'video')
  self.assertEqual(prune_private(archive,set())['files'],0)
  self.assertEqual(prune_private(archive,{'session-one'},apply=False)['files'],1);self.assertTrue(target.exists())
  self.assertEqual(prune_private(archive,{'session-one'})['files'],1);self.assertFalse(target.exists());self.assertTrue((folder/'receipt.json').exists())
 def test_clear_cutoff_releases_old_recording_without_waiting_for_discarded_analysis(self):
  folder=self.sessions/'20261104T000000-abcdef'
  save(folder/'manifest.json',dict(state='completed',capture_origin='provisional_motion',spool_generation='run-abc',stopped_epoch=2))
  save(folder/'buffer-state.json',dict(segments=[dict(start=0,end=10,file='segment-000000001.mkv')]))
  (folder/'video.mkv').write_bytes(b'original')
  save(self.data/'review-queue-cleared.json',dict(cutoff_epoch=10))
  legacy=self.event.parent/('b'*32);save(legacy/'event.json',dict(generation='run-abc',pts_seconds=5,created_epoch=1));(legacy/'object.png').write_bytes(b'unreviewed')
  cycle(self.data,self.sessions,{})
  self.assertFalse((folder/'video.mkv').exists());self.assertFalse((legacy/'object.png').exists());self.assertTrue(self.crop.exists())
 def test_clear_cutoff_never_discards_unverified_human_anomaly(self):
  folder=self.sessions/'20261104T000000-abcdef'
  save(folder/'manifest.json',dict(state='completed',capture_origin='provisional_motion',spool_generation='run-abc',stopped_epoch=2))
  save(folder/'buffer-state.json',dict(segments=[dict(start=0,end=10,file='segment-000000001.mkv')]))
  (folder/'video.mkv').write_bytes(b'original')
  save(self.data/'review-queue-cleared.json',dict(cutoff_epoch=10));save(self.crop.parent/'review.json',dict(self.record,label='anomalous'))
  cycle(self.data,self.sessions,{})
  self.assertTrue((folder/'video.mkv').exists());self.assertTrue((self.event/'review.mp4').exists())
 def test_unrelated_review_save_does_not_starve_object_cleanup(self):
  from unittest.mock import patch
  import review_retention as retention
  manifest=self.data/'email-reviews/training-manifest.json';save(manifest,dict(examples=[self.record]));original=retention.read;changed=[]
  def read(path,default=None):
   if path==self.event/'event.json' and not changed:
    changed.append(True);save(manifest,dict(examples=[self.record,dict(self.record,event_id='c'*32,sample_id='c'*32,reviewed_epoch=2)]))
   return original(path,default)
  with patch.object(retention,'read',read):result=cycle(self.data,self.sessions,{})
  self.assertEqual(result['deleted_files'],2);self.assertTrue(result['shared_cleanup_deferred']);self.assertTrue(self.crop.exists())
 def test_changed_target_review_blocks_object_cleanup(self):
  from unittest.mock import patch
  import review_retention as retention
  manifest=self.data/'email-reviews/training-manifest.json';save(manifest,dict(examples=[self.record]));original=retention.read;changed=[]
  def read(path,default=None):
   if path==self.event/'event.json' and not changed:
    changed.append(True);save(manifest,dict(examples=[dict(self.record,label='anomalous',reviewed_epoch=2)]))
   return original(path,default)
  with patch.object(retention,'read',read):result=cycle(self.data,self.sessions,{})
  self.assertEqual(result['deleted_files'],0);self.assertTrue((self.event/'review.mp4').exists())
if __name__=='__main__':unittest.main()
