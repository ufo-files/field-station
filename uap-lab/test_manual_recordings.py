import json,tempfile,unittest
from pathlib import Path
from manual_recordings import listing

class ManualRecordingsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.data=self.root/'lab';self.station=self.root/'station'
  (self.data/'live').mkdir(parents=True);(self.station/'sessions').mkdir(parents=True)
  self.records=[]
 def add(self,sid,state='completed',playback='completed',origin='manual'):
  folder=self.station/'sessions'/sid;folder.mkdir()
  self.records.append(dict(session_id=sid,created=len(self.records)))
  (self.data/'live/manual-sessions.json').write_text(json.dumps(self.records))
  (folder/'manifest.json').write_text(json.dumps(dict(id=sid,state=state,capture_origin=origin,started_epoch=len(self.records),elapsed_seconds=12,video_playback={'state':playback})))
  if playback=='completed':(folder/'video.mp4').write_bytes(b'video')
  return folder
 def test_ready_preparing_active_are_all_listed_without_training_labels(self):
  self.add('20261109T055133Z-704e15')
  self.add('20261109T055847Z-dbe797',playback='processing')
  self.add('20261109T061521Z-5f76f6',state='recording',playback='queued')
  result=listing(self.data,self.station)
  self.assertEqual([r['state'] for r in result['items']],['recording','preparing','ready'])
  self.assertIsNone(result['items'][0]['video_url']);self.assertIsNone(result['items'][1]['video_url'])
  self.assertIn('video.mp4',result['items'][2]['video_url'])
  self.assertTrue(all(r['label'] is None and not r['human_reviewed'] for r in result['items']))
  self.assertFalse((self.data/'email-reviews').exists())
 def test_approval_and_verified_archive_only(self):
  sid='20261109T055133Z-704e15';folder=self.add(sid)
  (folder/'manual-archive-approval.json').write_text(json.dumps(dict(session_id=sid,human_confirmed=True,classification='anomalous',upload_requested=True)))
  receipt=folder/'manual-internet-archive.json'
  for state in ['uploading','verified']:
   receipt.write_text(json.dumps(dict(state=state,url='https://archive.org/details/test-recording')))
   row=listing(self.data,self.station)['items'][0]
   self.assertEqual(row['label'],'anomalous');self.assertTrue(row['human_reviewed'])
   self.assertEqual(bool(row['archive_url']),state=='verified')
 def test_cursor_and_nonmanual_exclusion(self):
  self.add('20261109T055133Z-704e15');self.add('20261109T055847Z-dbe797')
  self.add('20261109T061521Z-5f76f6',origin='provisional_motion')
  first=listing(self.data,self.station,limit=1)
  second=listing(self.data,self.station,before=first['next_cursor'],limit=1)
  self.assertEqual(first['total'],2);self.assertNotEqual(first['items'][0]['id'],second['items'][0]['id'])
  self.assertIsNone(second['next_cursor'])
 def test_removed_manifest_and_invalid_ids_are_not_links(self):
  self.records=[{'session_id':'../../secret'},{'session_id':'20261109T055133Z-704e15'}]
  (self.data/'live/manual-sessions.json').write_text(json.dumps(self.records))
  self.assertEqual(listing(self.data,self.station)['items'],[])

class ManualReviewTests(ManualRecordingsTests):
 def setup_review(self):
  sid='20261109T055133Z-704e15';folder=self.add(sid)
  manifest=json.loads((folder/'manifest.json').read_text());# Manual sessions may have no spool_generation field.
  manifest.pop('spool_generation',None)
  (folder/'manifest.json').write_text(json.dumps(manifest))
  (folder/'buffer-state.json').write_text(json.dumps({'segments':[{'start':100,'end':101}]}))
  # Production's notifications and sessions share the external data root.
  (self.root/'sessions').symlink_to(self.station/'sessions',target_is_directory=True)
  return sid,folder
 def test_registration_is_suppressed_unclassified_and_idempotent(self):
  from manual_recordings import register_review
  sid,folder=self.setup_review();key=register_review(self.data,self.station,sid)
  workspace=self.root/'notifications/outbox'/key
  event=json.loads((workspace/'event.json').read_text())
  self.assertIsNone(event['classification']);self.assertIsNone(event['bounds'])
  self.assertEqual(json.loads((workspace/'delivery.json').read_text())['state'],'suppressed')
  self.assertEqual(register_review(self.data,self.station,sid),key)
  self.assertFalse((self.data/'email-reviews').exists())
 def test_selected_frame_crop_uses_native_recording(self):
  import av,numpy as np,shutil,io
  from unittest.mock import patch
  from PIL import Image
  from manual_recordings import register_review,prepare_review
  from email_review import save_review
  sid,folder=self.setup_review()
  with av.open(str(folder/'video.mp4'),'w') as output:
   stream=output.add_stream('libx264',rate=30);stream.width=64;stream.height=48;stream.pix_fmt='yuv420p'
   for i in range(3):
    pixels=np.zeros((48,64,3),dtype=np.uint8);pixels[:,:,i]=180
    frame=av.VideoFrame.from_ndarray(pixels,format='rgb24')
    for packet in stream.encode(frame):output.mux(packet)
   for packet in stream.encode():output.mux(packet)
  key=register_review(self.data,self.station,sid);workspace=self.root/'notifications/outbox'/key
  def preview(source,target,**kwargs):
   shutil.copyfile(source,target);return {'playback_frames_verified':True}
  with patch.dict('os.environ',{'XDG_RUNTIME_DIR':''}),patch('review_playback.build_preview',side_effect=preview):
   info=prepare_review(self.data,key,workspace,workspace)
   self.assertEqual((workspace/'review.mp4').stat().st_ino,(folder/'video.mp4').stat().st_ino)
   seconds=info['timeline'][1]['time'];bounds=[5,6,20,18]
   with patch('review_archive.invalidate_event'),patch('email_review.finish_review'):
    saved=save_review(self.data,dict(id=key,label='anomalous',time=seconds,bounds=bounds))
   self.assertEqual(saved['review']['review_clip_time'],seconds)
   self.assertEqual(saved['review']['bounds'],bounds)
   with av.open(str(folder/'video.mp4')) as source:expected=list(source.decode(video=0))[1].to_image().crop((5,6,25,24))
   crop=self.data/'email-reviews/examples'/saved['review']['sample_id']/'native-object.png'
   with Image.open(crop) as actual:self.assertEqual(actual.tobytes(),expected.tobytes())

if __name__=='__main__':unittest.main()
