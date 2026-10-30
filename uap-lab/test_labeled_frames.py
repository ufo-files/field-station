import json,sys,tempfile,threading,types,unittest
from pathlib import Path
from unittest.mock import patch
import labeled_frames
class LabelsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'data';self.station=self.root/'station';self.vid='a'*32;self.aid='b'*32
  self.folder=self.data/'videos'/self.vid;self.folder.mkdir(parents=True);self.session=self.station/'sessions/20261029T120000Z-abcdef';self.session.mkdir(parents=True)
  def read(p,default=None):
   try:return json.loads(p.read_text())
   except FileNotFoundError:return default
  def save(p,v):p.write_text(json.dumps(v))
  def checked(v):
   if len(v)!=32 or any(c not in 'abcdef0123456789' for c in v):raise ValueError('invalid id')
   return v
  self.lab=types.SimpleNamespace(DATA=self.data,STATION=self.station,LOCK=threading.Lock(),_REVIEW_LOCKS={},_per_video_lock=lambda *_:threading.Lock(),read=read,save=save,checked_id=checked,video_path=lambda v:self.data/'videos'/checked(v))
  self.patch=patch.dict(sys.modules,{'lab':self.lab});self.patch.start()
  save(self.folder/'video.json',dict(id=self.vid,name='Test recording',sha256='hash',created=1,provenance={'session_id':self.session.name}))
  save(self.folder/'annotations.json',[dict(id=self.aid,label='anomalous',time=1.2,image=self.aid+'.png')]);save(self.folder/'review.json',{'completed':True});save(self.session/'manifest.json',{'state':'completed'})
  (self.folder/(self.aid+'.png')).write_bytes(b'crop');(self.folder/'source').write_bytes(b'original')
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def test_listing_filter_pagination_and_omitted_labels(self):
  self.lab.save(self.folder/'training-excluded.json',{'excluded':True})
  result=labeled_frames.listing(search='test',limit=1);self.assertEqual(result['total'],1);self.assertTrue(result['items'][0]['excluded']);self.assertEqual(labeled_frames.listing(label='bird')['total'],0)
 def test_remove_audits_preserves_original_and_revokes_review(self):
  out=labeled_frames.remove(self.vid,self.aid);self.assertEqual(out['annotations'],[])
  self.assertFalse(self.lab.read(self.folder/'review.json')['completed']);self.assertFalse(self.lab.read(self.session/'archive-decision.json')['human_confirmed']);self.assertFalse(self.lab.read(self.data/'reviewed-videos.json')['hash']['completed'])
  self.assertEqual(len(list((self.folder/'annotation-history').glob('*.json'))),1);self.assertEqual((self.folder/'source').read_bytes(),b'original');self.assertTrue((self.folder/(self.aid+'.png')).exists())
 def test_missing_annotation_does_not_revoke_review(self):
  with self.assertRaises(ValueError):labeled_frames.remove(self.vid,'c'*32)
  self.assertTrue(self.lab.read(self.folder/'review.json')['completed'])
 def test_bad_ids_rejected(self):
  with self.assertRaises(ValueError):labeled_frames.remove('../escape',self.aid)
if __name__=='__main__':unittest.main()
