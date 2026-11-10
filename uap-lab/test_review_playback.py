import hashlib,json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

class ReviewPlaybackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.data=self.root/'lab';self.data.mkdir();self.key='a'*32
  self.ffmpeg=shutil.which('ffmpeg')
  if not self.ffmpeg:self.skipTest('ffmpeg unavailable')
  self.env=patch.dict(os.environ,UAP_LAB_DATA=str(self.data),XDG_RUNTIME_DIR=str(self.root/'fast'),FFMPEG=self.ffmpeg);self.env.start();self.addCleanup(self.env.stop)
  self.folder=self.root/'notifications/outbox'/self.key;self.folder.mkdir(parents=True);self.spool=self.root/'capture-spool/run-abc';self.spool.mkdir(parents=True)
  source=self.spool/'segment-000000001.mkv'
  subprocess.run([self.ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=96x64:rate=30','-t','1','-c:v','libx264','-threads','1','-g','1','-bf','0',str(source)],check=True)
  e=dict(file=source.name,start=0,end=1,sha256=hashlib.sha256(source.read_bytes()).hexdigest())
  (self.spool/'segments-index.jsonl').write_text(json.dumps(e)+'\n');(self.spool/'closed.json').write_text('{}')
  (self.folder/'event.json').write_text(json.dumps(dict(generation='run-abc',pts_seconds=.5,bounds=[1,2,8,8],model='m')))
 def test_prepare_uses_encoded_verification_and_original_for_training(self):
  import email_review,review_playback
  with patch('email_review.decoded_frames',side_effect=AssertionError('No full pixel decode during preparation')):result=email_review.prepare(self.data,self.key)
  self.assertTrue(result['source_frames_verified']);self.assertTrue(result['playback_frames_verified']);self.assertEqual(result['frames'],30)
  native=review_playback.native_path(self.data,self.key);preview=review_playback.playback_path(self.data,self.key)
  self.assertNotEqual(native,preview);self.assertTrue(str(native).startswith(str(self.root/'fast')))
  self.assertEqual([p['data_hash'] for p in email_review.decoded_frames(native)],[p['data_hash'] for p in email_review.decoded_frames(self.spool/'segment-000000001.mkv')])
  self.assertEqual(len(review_playback.frame_times(preview)),30)
  with patch('email_review.build_preview',side_effect=AssertionError('Warm clip must not rebuild')):self.assertEqual(email_review.prepare(self.data,self.key),result)
  with patch('email_review.store_review',return_value='imported'),patch('email_review.invalidate_event',create=True):
   saved=email_review.save_review(self.data,dict(id=self.key,label='anomalous',time=result['event_time'],bounds=[1,2,8,8]))
  self.assertEqual(saved['review']['bounds'],[1,2,8,8])
 def test_corrupt_source_rejected_before_publication(self):
  from email_review import prepare
  (self.spool/'segment-000000001.mkv').write_bytes(b'bad')
  with self.assertRaisesRegex(ValueError,'checksum'):prepare(self.data,self.key)
  self.assertFalse((self.folder/'review-clip.json').exists())
 def test_native_path_is_stable_after_retention(self):
  from email_review import prepare
  from review_playback import native_path
  prepare(self.data,self.key);path=native_path(self.data,self.key);path.unlink();self.assertEqual(native_path(self.data,self.key),path)
 def test_omit_deletes_fast_ssd_video_copies(self):
  from email_review import prepare
  from review_playback import media_dir
  from object_omission import omit
  prepare(self.data,self.key);folder=media_dir(self.data,self.key)
  self.assertTrue((folder/'playback.mp4').exists());omit(self.data,dict(id=self.key));self.assertFalse((folder/'review.mp4').exists());self.assertFalse((folder/'playback.mp4').exists())

 def test_preparation_does_not_wait_for_global_cleanup_lease(self):
  import fcntl
  from email_review import prepare
  with (self.data/'review-media.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   self.assertEqual(prepare(self.data,self.key)['state'],'ready')
 def test_event_lease_protects_only_the_active_detection(self):
  from review_playback import event_lease
  from object_omission import omit
  with event_lease(self.folder) as available:
   self.assertTrue(available)
   with self.assertRaisesRegex(ValueError,'preparation'):omit(self.data,dict(id=self.key))

 def test_preview_preserves_fractional_camera_timestamps(self):
  from review_playback import build_preview,frame_times
  source=self.root/'camera.mp4';target=self.root/'preview.mp4'
  subprocess.run([self.ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=96x64:rate=60000/1001','-t','0.4','-c:v','libx264','-threads','1','-g','1','-bf','0',str(source)],check=True)
  build_preview(source,target)
  self.assertEqual(len(frame_times(source)),len(frame_times(target)))
  self.assertTrue(all(abs(a-b)<.003 for a,b in zip(frame_times(source),frame_times(target))))

class CrossVolumePinTests(unittest.TestCase):
 def test_cross_device_pin_copies_complete_bytes(self):
  import errno
  from unittest.mock import patch
  from review_playback import pin_segment
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source';target=Path(d)/'pin';source.write_bytes(b'original encoded segment')
   with patch('review_playback.os.link',side_effect=OSError(errno.EXDEV,'Cross-device link')):pin_segment(source,target)
   self.assertEqual(target.read_bytes(),source.read_bytes())
 def test_other_io_errors_are_not_hidden(self):
  import errno
  from unittest.mock import patch
  from review_playback import pin_segment
  with patch('review_playback.os.link',side_effect=OSError(errno.ENOSPC,'full')),patch('shutil.copyfile') as copy:
   with self.assertRaises(OSError):pin_segment('source','target')
   copy.assert_not_called()
