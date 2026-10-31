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
 def test_gallery_includes_preserved_and_email_web_reviews(self):
  preserved=self.root/'preserved';folder=preserved/'videos'/('c'*32);folder.mkdir(parents=True)
  self.lab.save(folder/'video.json',dict(name='PURSUE original',created=0,provenance={'collection':'PURSUE'}))
  self.lab.save(folder/'annotations.json',[dict(id='d'*32,label='star',time=2,image='crop.png')]);(folder/'crop.png').write_bytes(b'preserved')
  for sid,source in [('e'*32,'owner_email_reply'),('f'*32,'station_web_review')]:
   example=self.data/'email-reviews/examples'/sid;example.mkdir(parents=True)
   self.lab.save(example/'review.json',dict(event_id='1'*32,label='cloud',human_confirmed=True,multiclass_ready=True,source=source));(example/'native-object.png').write_bytes(b'review')
  with patch.object(labeled_frames,'preserved_root',return_value=preserved):
   result=labeled_frames.listing();self.assertEqual(result['total'],4);self.assertEqual(result['labels']['cloud'],2)
   self.assertEqual(labeled_frames.listing(search='PURSUE')['total'],1)
   self.assertEqual(labeled_frames.listing(label='pursue')['total'],1)
   self.assertEqual(labeled_frames.listing(label='pursue')['items'][0]['annotation']['label'],'star')
   self.assertEqual(result['groups']['pursue'],1)
   self.assertEqual(labeled_frames.gallery_image('preserved','c'*32,'d'*32).read_bytes(),b'preserved')
   self.assertEqual(labeled_frames.gallery_image('review','1'*32,'e'*32).read_bytes(),b'review')
   with self.assertRaises(ValueError):labeled_frames.gallery_image('review','2'*32,'e'*32)
   # Current labels and deletions take precedence over preserved copies.
   current=self.data/'videos'/('c'*32);current.mkdir();self.lab.save(current/'video.json',{'name':'current'})
   self.lab.save(current/'annotations.json',[]);self.assertEqual(labeled_frames.listing()['total'],3)
 def test_hundred_item_pages_and_full_filter_counts(self):
  annotations=[dict(id=f'{i:032x}',label='cloud' if i<150 else 'star',time=i,image='crop.png') for i in range(250)]
  self.lab.save(self.folder/'annotations.json',annotations)
  first=labeled_frames.listing(limit=100);second=labeled_frames.listing(offset=100,limit=100)
  self.assertEqual(len(first['items']),100);self.assertEqual(len(second['items']),100)
  self.assertEqual(first['total'],250);self.assertEqual(first['labels'],{'cloud':150,'star':100})
  self.assertNotEqual(first['items'][0]['annotation']['id'],second['items'][0]['annotation']['id'])
  filtered=labeled_frames.listing(label='star',video='video:'+self.vid)
  self.assertEqual(filtered['total'],100);self.assertEqual(filtered['labels']['cloud'],150)
 def test_field_station_anomalies_exclude_imports_and_automated_labels(self):
  for i,collection,automated in [(1,'PURSUE',False),(2,'training-data',False),(3,'motion-collection',True),(4,'recorded-clip',False)]:
   folder=self.data/'videos'/f'{i:032x}';folder.mkdir()
   self.lab.save(folder/'video.json',dict(name=collection,provenance=dict(collection=collection)))
   self.lab.save(folder/'annotations.json',[dict(id=f'{i+10:032x}',label='anomalous',time=0,image='crop.png')])
   self.lab.save(folder/'review.json',dict(automated_event=automated))
  for i,source,label,deleted in [(5,'owner_email_reply','anomalous',False),(6,'station_web_review','anomalous',False),(7,'station_web_review','cloud',False),(8,'owner_email_reply','anomalous',True)]:
   folder=self.data/'email-reviews/examples'/f'{i:032x}';folder.mkdir(parents=True)
   self.lab.save(folder/'review.json',dict(event_id='1'*32,source=source,label=label,human_confirmed=True,deleted=deleted))
  result=labeled_frames.listing(label='anomalous_field_station',limit=2)
  self.assertEqual(result['total'],4);self.assertEqual(len(result['items']),2);self.assertEqual(result['groups']['anomalous_field_station'],4)
  self.assertEqual(result['labels']['anomalous'],7)
  self.assertTrue(all(r['field_station'] and r['annotation']['label']=='anomalous' for r in result['items']))
  self.assertEqual(labeled_frames.listing(label='anomalous_field_station',offset=2)['total'],4)
 def test_bad_ids_rejected(self):
  with self.assertRaises(ValueError):labeled_frames.remove('../escape',self.aid)
if __name__=='__main__':unittest.main()
