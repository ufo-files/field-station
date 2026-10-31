import hashlib,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
import label_queue
class QueueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'lab';self.data.mkdir()
  b=io.BytesIO();Image.new('RGB',(32,32),'white').save(b,format='PNG');self.crop=b.getvalue()
  for i in range(1,4):
   key=f'{i:032x}';p=self.root/'notifications/outbox'/key;p.mkdir(parents=True)
   e=dict(id=key,created_epoch=i,generation='run-abc',sequence=i,pts_seconds=i,bounds=[1,2,32,32],model='model',native_crop='native-object.png',native_crop_sha256=hashlib.sha256(self.crop).hexdigest())
   (p/'event.json').write_text(json.dumps(e));(p/'native-object.png').write_bytes(self.crop);(p/'object.png').write_bytes(self.crop)
 def tearDown(self):self.tmp.cleanup()
 def test_label_is_human_training_data_not_session_completion(self):
  key=f'{3:032x}';body=dict(id=key,label='cloud',request_id='a'*32)
  label_queue.label(self.data,body);label_queue.label(self.data,body)
  r=json.loads((self.data/'email-reviews/examples'/key/'review.json').read_text())
  self.assertTrue(r['human_confirmed']);self.assertEqual(r['source'],'station_web_review');self.assertEqual(r['label'],'cloud')
  self.assertEqual(len(list((self.data/'email-reviews/history').glob('*.json'))),1)
  self.assertFalse((self.root/'notifications/outbox'/key/'review-completion.json').exists())
  self.assertEqual(label_queue.listing(self.data)['total'],2)
  with self.assertRaisesRegex(ValueError,'already been reviewed'):label_queue.label(self.data,dict(body,request_id='b'*32,label='bird'))
 def test_cursor_does_not_skip_after_labeling(self):
  first=label_queue.listing(self.data,limit=1)
  label_queue.label(self.data,dict(id=first['items'][0]['id'],label='anomalous',request_id='a'*32))
  next_page=label_queue.listing(self.data,before=first['next_cursor'],limit=1)
  self.assertEqual(next_page['items'][0]['id'],f'{2:032x}')
 def test_new_categories_are_available_and_save(self):
  self.assertTrue({'house','antenna','vehicle'}<=set(label_queue.listing(self.data)['labels']))
  for i,category in enumerate(('house','antenna','vehicle'),1):
   self.assertTrue(label_queue.label(self.data,dict(id=f'{i:032x}',label=category,request_id=f'{i+10:032x}'))['saved'])
 def test_historical_backlog_scan_is_bounded(self):
  for i in range(100,701):
   folder=self.root/'notifications/outbox'/f'{i:032x}';folder.mkdir()
   (folder/'event.json').write_text('{}');(folder/'delivery.json').write_text('{"state":"cancelled"}')
  first=label_queue.listing(self.data)
  self.assertEqual(first['items'],[]);self.assertIsNotNone(first['next_cursor'])
  second=label_queue.listing(self.data,before=first['next_cursor'])
  self.assertEqual(len(second['items']),3);self.assertIsNone(second['next_cursor'])
 def test_invalid_labels_tampering_and_expired_backlog(self):
  key=f'{1:032x}';body=dict(id=key,label='made_up',request_id='a'*32)
  with self.assertRaises(ValueError):label_queue.label(self.data,body)
  path=self.root/'notifications/outbox'/key;(path/'native-object.png').write_bytes(b'tampered')
  with self.assertRaisesRegex(ValueError,'checksum'):label_queue.label(self.data,dict(body,label='bird'))
  (path/'delivery.json').write_text('{"state":"cancelled"}');self.assertEqual(label_queue.listing(self.data)['total'],2)
  with self.assertRaises(ValueError):label_queue.image_path(self.data,'../escape')
if __name__=='__main__':unittest.main()
