import json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
import lab,archive_exports as exports
from archive_policy import eligible
from email_review import annotation_revision
SID='20261031T083753Z-04be18'
class ExportTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.data=self.root/'uap-lab';self.sessions=self.root/'sessions';self.folder=self.sessions/SID;self.folder.mkdir(parents=True);(self.data/'videos').mkdir(parents=True)
 def tearDown(self):self.temp.cleanup()
 def test_only_completed_current_web_reviews_group_all_objects_into_one_session(self):
  lab.save(self.folder/'manifest.json',dict(id=SID,spool_generation='g'));lab.save(self.folder/'buffer-state.json',dict(segments=[dict(start=10,end=30)]))
  key='a'*32;out=self.root/'notifications/outbox'/key;out.mkdir(parents=True);lab.save(out/'event.json',dict(generation='g',pts_seconds=20))
  for i,source in enumerate(['station_web_review','station_web_review','owner_email_reply']):
   f=self.data/'email-reviews/examples'/str(i);f.mkdir(parents=True);lab.save(f/'review.json',dict(event_id=key,sample_id=str(i),source=source,label='anomalous',human_confirmed=True,reviewed_epoch=i))
  self.assertEqual(exports.collect(self.data,self.sessions)[0],{})
  lab.save(out/'review-completion.json',dict(completed=True,updated_epoch=10,annotation_revision=annotation_revision(self.data,key)))
  groups,errors=exports.collect(self.data,self.sessions);self.assertFalse(errors);self.assertEqual(list(groups),[SID]);self.assertEqual(len(groups[SID][0]['annotations']),2)
  row=self.data/'email-reviews/examples/0/review.json';d=lab.read(row);d['reviewed_epoch']=99;lab.save(row,d);self.assertFalse(exports.collect(self.data,self.sessions)[0])
 def test_export_keeps_native_frames_and_both_boxes_without_changing_raw(self):
  raw=self.folder/'video.mkv'
  exports.command([lab.FFMPEG,'-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=10:duration=1','-vf',r'settb=1/1000,setpts=PTS+mod(N\,3)','-enc_time_base:v','1:1000','-fps_mode','passthrough','-c:v','libx264','-pix_fmt','yuv420p',str(raw)])
  before=hashlib.sha256(raw.read_bytes()).hexdigest()
  points=[dict(id='1',label='anomalous',time=.2,bounds=dict(x=.1,y=.1,w=.2,h=.2)),dict(id='2',label='star',time=.2,bounds=dict(x=.6,y=.6,w=.2,h=.2))]
  groups=[dict(id='a',kind='video',source=str(raw),annotations=points)]
  boxes,frames,w,h=exports.align_annotations(raw,groups);self.assertEqual([b['frame'] for b in boxes],[2,2])
  exports.render(self.folder,raw,boxes,frames,w,h)
  import av,numpy as np
  with av.open(str(raw)) as c:original=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
  with av.open(str(self.folder/'video-annotated.mp4')) as c:annotated=[f.to_ndarray(format='rgb24') for f in c.decode(video=0)]
  self.assertEqual(len(original),len(annotated));self.assertEqual(before,hashlib.sha256(raw.read_bytes()).hexdigest())
  for x,y in [(32,24),(192,144)]:self.assertGreater(np.abs(annotated[2][y:y+4,x:x+64].astype(float)-original[2][y:y+4,x:x+64]).mean(),20)
  self.assertLess(np.abs(annotated[0].astype(float)-original[0]).mean(),5)
 def test_email_manual_and_withdrawn_never_authorize_publication(self):
  d=dict(schema=2,source='station_web_ui',session_id=SID,human_confirmed=True,confirmed_anomalous=True,bundle_ready=True,videos=['video.mp4','video-annotated.mp4'],reviewed_epoch=1)
  m=dict(id=SID,capture_origin='manual');self.assertFalse(eligible(m));self.assertTrue(eligible(m,d))
  for source in ['owner_email_reply','model','station_web_review']:self.assertFalse(eligible(m,dict(d,source=source)))
  self.assertFalse(eligible(dict(m,archive_withdrawn=True),d));self.assertFalse(eligible(m,dict(d,bundle_ready=False)))
