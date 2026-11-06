import hashlib,json,math,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import lab,video_trim,archive_exports
from recognition_review import packets
SID='20261106T021933Z-b3ccb7';KEY='a'*32
class TrimTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.data=self.root/'uap-lab';self.folder=self.root/'sessions'/SID;self.out=self.root/'notifications/outbox'/KEY
  for p in (self.folder,self.out,self.data/'email-reviews'):p.mkdir(parents=True)
  lab.save(self.data/'archive-review-groups.json',dict(groups={SID:[dict(kind='alert_web',id=KEY)]}))
  lab.save(self.out/'event.json',dict(generation='run-test',pts_seconds=.2));self.timeline=[dict(time=i/10,source_pts=100+i/10) for i in range(10)]
  lab.save(self.out/'review-clip.json',dict(source_frames_verified=True,timeline=self.timeline))
  lab.save(self.folder/'archive-decision.json',dict(bundle_ready=True));self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':str(self.root/'runtime')});self.env.start()
 def tearDown(self):self.env.stop();self.temp.cleanup()
 def test_range_validation_and_reversible_metadata(self):
  for start,end in [(float('nan'),.7),(.7,.2),(-1,.4),(.2,3),(.2,.2)]:
   with self.assertRaises(ValueError):video_trim.save(self.data,dict(id=KEY,start=start,end=end))
  result=video_trim.save(self.data,dict(id=KEY,start=.2,end=.7));self.assertTrue(result['saved']);self.assertEqual(result['request']['start_frame'],2);self.assertEqual(result['request']['end_frame'],7)
  self.assertFalse(lab.read(self.folder/'archive-decision.json')['bundle_ready']);self.assertFalse(result['applied'])
  old=result['request']['revision'];reset=video_trim.save(self.data,dict(id=KEY,reset=True));self.assertFalse(reset['request']['enabled']);self.assertTrue((self.folder/'trim-history'/(old+'.json')).is_file())
 def test_encoded_frames_annotation_offsets_and_restore(self):
  raw=self.folder/'video.mkv';archive_exports.command([lab.FFMPEG,'-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=10:duration=1','-c:v','libx264','-g','1','-bf','0',str(raw)])
  archive_exports.command([lab.FFMPEG,'-v','error','-i',str(raw),'-c','copy',str(self.out/'review.mp4')])
  before=hashlib.sha256(raw.read_bytes()).hexdigest();video_trim.save(self.data,dict(id=KEY,start=.2,end=.7))
  annotations=[dict(frame=2,bounds=[20,20,30,30],label='anomalous'),dict(frame=8,bounds=[40,40,30,30],label='not_anomalous')]
  path,boxes,count=video_trim.apply(self.folder,raw,annotations);self.assertEqual(count,5);self.assertEqual([a['frame'] for a in boxes],[0]);self.assertEqual([a['frame'] for a in annotations],[2,8]);self.assertEqual(len(packets(path)),5)
  archive_exports.render(self.folder,path,boxes,count,320,240);self.assertEqual(len(packets(self.folder/'video-annotated.mp4')),5)
  index=archive_exports.render_stills(self.folder,raw,annotations,320,240,'b'*64);self.assertEqual(len(index['frames']),2)
  self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(),before)
  video_trim.save(self.data,dict(id=KEY,reset=True));path,boxes,count=video_trim.apply(self.folder,raw,annotations);self.assertEqual(count,10);self.assertEqual([a['frame'] for a in boxes],[2,8]);self.assertEqual(len(packets(path)),10)
 def test_download_waits_for_current_trim_revision(self):
  result=video_trim.save(self.data,dict(id=KEY,start=.2,end=.7))
  with self.assertRaisesRegex(ValueError,'preparing'):video_trim.download(self.data,KEY)
  (self.folder/'video.mp4').write_bytes(b'video');lab.save(self.folder/'archive-decision.json',dict(bundle_ready=True,trim_revision=result['request']['revision']))
  self.assertEqual(video_trim.download(self.data,KEY),self.folder/'video.mp4')

 def test_superseded_export_retries_without_false_error(self):
  result=video_trim.save(self.data,dict(id=KEY,start=.2,end=.7))
  lab.save(self.data/'archive-review-status.json',dict(updated_epoch=result['request']['saved_epoch']+1,sessions=[dict(session_id=SID,state='blocked',error='Review changed during export; awaiting updated export')]))
  status=video_trim.status(self.data,KEY);self.assertFalse(status['applied']);self.assertIsNone(status['error'])
  lab.save(self.data/'archive-review-status.json',dict(updated_epoch=result['request']['saved_epoch']+2,sessions=[dict(session_id=SID,state='blocked',error='Actual export failure')]))
  self.assertEqual(video_trim.status(self.data,KEY)['error'],'Actual export failure')
  lab.save(self.folder/'archive-decision.json',dict(bundle_ready=True,trim_revision=result['request']['revision']))
  status=video_trim.status(self.data,KEY);self.assertTrue(status['applied']);self.assertIsNone(status['error'])
