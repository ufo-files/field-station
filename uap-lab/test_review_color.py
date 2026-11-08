import json,os,tempfile,unittest,hashlib,shutil
from pathlib import Path
from unittest.mock import patch
import av,numpy as np
from PIL import Image
import review_color

class ColorReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.folder=self.root/'notifications/outbox'/('a'*32);self.folder.mkdir(parents=True)
  self.segment=self.root/'capture-spool/run-abc/segment-000000000.mkv';self.segment.parent.mkdir(parents=True)
  with av.open(str(self.segment),'w') as out:
   stream=out.add_stream('libx264',rate=10);stream.width=64;stream.height=64;stream.pix_fmt='yuv420p';stream.options={'g':'1','bf':'0'}
   for color in [(255,0,0),(0,0,255),(0,255,0)]:
    image=np.zeros((64,64,3),dtype=np.uint8);image[:]=color
    for packet in stream.encode(av.VideoFrame.from_ndarray(image,format='rgb24')):out.mux(packet)
   for packet in stream.encode():out.mux(packet)
  with av.open(str(self.segment)) as source:frames=list(source.decode(video=0))
  self.seconds=float(frames[1].pts*frames[1].time_base)
  Image.fromarray(frames[1].to_ndarray(format='gray')).convert('RGB').save(self.folder/'source-frame.png')
  shutil.copyfile(self.folder/'source-frame.png',self.folder/'native-object.png')
  self.event=dict(native_crop_sha256=hashlib.sha256((self.folder/'native-object.png').read_bytes()).hexdigest(),generation='run-abc',pts_seconds=self.seconds,bounds=[0,0,64,64],review_color_source=dict(file=self.segment.name,pts_seconds=self.seconds))
  (self.folder/'event.json').write_text(json.dumps(self.event))
 def tearDown(self):self.tmp.cleanup()
 def test_color_comes_from_exact_frame_without_changing_training(self):
  before={n:(self.folder/n).read_bytes() for n in ['source-frame.png','native-object.png','event.json']}
  self.assertTrue(review_color.build(self.folder))
  image=np.asarray(Image.open(self.folder/'color-frame.jpg'));self.assertGreater(float(image[:,:,2].mean()),float(image[:,:,0].mean())+100)
  for name,data in before.items():self.assertEqual((self.folder/name).read_bytes(),data)
  self.assertTrue((self.folder/'color-detail.jpg').is_file())
 def test_wrong_frame_is_not_substituted(self):
  self.event['review_color_source']['pts_seconds']=0;(self.folder/'event.json').write_text(json.dumps(self.event))
  self.assertFalse(review_color.build(self.folder));self.assertFalse((self.folder/'color-detail.jpg').exists())
 def test_restored_review_clip_can_supply_color(self):
  self.segment.rename(self.folder/'review.mp4');(self.folder/'review-clip.json').write_text(json.dumps(dict(state='ready',event_time=self.seconds)))
  with patch.dict(os.environ,{},clear=True):self.assertTrue(review_color.build(self.folder))
 def test_cleared_detection_is_not_regenerated(self):
  (self.folder/'label-queue-dismissed.json').write_text('{}');self.assertFalse(review_color.build(self.folder));self.assertFalse((self.folder/'color-detail.jpg').exists())

 def test_verified_color_sidecar_enters_training_without_rewriting_review(self):
  from email_training import reviewed_examples
  self.assertTrue(review_color.build(self.folder));data=self.root/'uap-lab';example=data/'email-reviews/examples'/self.folder.name;example.mkdir(parents=True)
  review=dict(event_id=self.folder.name,sample_id=self.folder.name,label='anomalous',human_confirmed=True,generation='run-abc',bounds=self.event['bounds'],native_crop_sha256=self.event['native_crop_sha256'])
  (example/'review.json').write_text(json.dumps(review))
  for name in ['native-object.png','color-native-object.png','color-review.json']:shutil.copyfile(self.folder/name,example/name)
  result=reviewed_examples(data,prepared=True)[0]
  self.assertEqual(result['color_provenance'],'verified_color_recovery');self.assertEqual(result['label'],'anomalous');self.assertEqual(json.loads((example/'review.json').read_text()),review)
  (example/'color-native-object.png').write_bytes(b'corrupt')
  with self.assertRaisesRegex(ValueError,'Recovered color crop integrity'):reviewed_examples(data)
