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
if __name__=='__main__':unittest.main()
