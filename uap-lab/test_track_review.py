import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import lab
from track_review import link
class TrackReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name);self.vid='a'*32;self.folder=self.data/'videos'/self.vid;self.folder.mkdir(parents=True);self.patch=patch.object(lab,'DATA',self.data);self.patch.start()
  lab.save(self.folder/'video.json',dict(id=self.vid,sha256='b'*64));self.rows=[dict(id=str(i)*32,time=i/60,frame_index=i,label='bird',track_id=str(i+4)*32,image=str(i)*32+'.png') for i in range(1,4)]
  lab.save(self.folder/'annotations.json',self.rows);lab.save(self.folder/'review.json',{'completed':True,'reviewed_at':10});lab.save(self.data/'reviewed-videos.json',{'b'*64:{'completed':True,'reviewed_at':10}})
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def test_link_preserves_labels_images_and_review_sha_history(self):
  before=(self.data/'reviewed-videos.json').read_bytes();review=(self.folder/'review.json').read_bytes();r=link(self.vid,[a['id'] for a in self.rows]);self.assertEqual(r['observations'],3);self.assertEqual(len({a['track_id'] for a in r['annotations']}),1)
  self.assertEqual(before,(self.data/'reviewed-videos.json').read_bytes());self.assertEqual(review,(self.folder/'review.json').read_bytes());self.assertEqual([a['image'] for a in r['annotations']],[a['image'] for a in self.rows])
  history=list((self.folder/'track-history').glob('*.json'));self.assertEqual(len(history),1);self.assertEqual(lab.read(history[0])['before'],self.rows)
 def test_different_labels_and_same_native_frame_are_rejected(self):
  self.rows[1]['label']='airplane';lab.save(self.folder/'annotations.json',self.rows)
  with self.assertRaisesRegex(ValueError,'one label'):link(self.vid,[a['id'] for a in self.rows])
  self.rows[1]['label']='bird';self.rows[1]['frame_index']=1;lab.save(self.folder/'annotations.json',self.rows)
  with self.assertRaisesRegex(ValueError,'native frame'):link(self.vid,[a['id'] for a in self.rows])
 def test_duplicate_or_missing_selection_never_rewrites(self):
  original=(self.folder/'annotations.json').read_bytes()
  for ids in ([self.rows[0]['id']]*2,[self.rows[0]['id'],'f'*32]):
   with self.assertRaises(ValueError):link(self.vid,ids)
  self.assertEqual(original,(self.folder/'annotations.json').read_bytes())
