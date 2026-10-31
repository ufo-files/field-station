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
  self.assertTrue({'house','antenna','vehicle','telephone_pole','mountain','landscape'}<=set(label_queue.listing(self.data)['labels']))
  for i,category in enumerate(('house','antenna','vehicle'),1):
   self.assertTrue(label_queue.label(self.data,dict(id=f'{i:032x}',label=category,request_id=f'{i+10:032x}'))['saved'])
 def test_telephone_pole_can_be_saved(self):
  result=label_queue.label(self.data,dict(id=f'{1:032x}',label='telephone_pole',request_id='a'*32))
  self.assertEqual(result['label'],'telephone_pole')
 def test_mountain_can_be_saved(self):
  result=label_queue.label(self.data,dict(id=f'{1:032x}',label='mountain',request_id='a'*32))
  self.assertEqual(result['label'],'mountain')
 def test_historical_backlog_scan_is_bounded(self):
  for i in range(100,701):
   folder=self.root/'notifications/outbox'/f'{i:032x}';folder.mkdir()
   (folder/'event.json').write_text('{}');(folder/'delivery.json').write_text('{"state":"cancelled"}')
  first=label_queue.listing(self.data)
  self.assertEqual(first['items'],[]);self.assertIsNotNone(first['next_cursor'])
  second=label_queue.listing(self.data,before=first['next_cursor'])
  self.assertEqual(len(second['items']),3);self.assertIsNone(second['next_cursor'])
 def test_unified_queue_includes_only_actionable_videos(self):
  for i in range(10,14):
   folder=self.data/'videos'/f'{i:032x}';folder.mkdir(parents=True)
   (folder/'video.json').write_text(json.dumps(dict(id=folder.name,name='Recorded clip',sha256=str(i),media_expired=i==13)))
   (folder/'source').write_bytes(b'video')
   (folder/'review.json').write_text(json.dumps(dict(completed=i==11)))
   (folder/'training-excluded.json').write_text(json.dumps(dict(excluded=i==12)))
  first=label_queue.listing(self.data,limit=3)
  self.assertEqual(first['next_cursor'],'v:')
  second=label_queue.listing(self.data,before=first['next_cursor'])
  self.assertEqual(len(second['items']),1);self.assertEqual(second['items'][0]['kind'],'video')
  self.assertIn('view=label&video=',second['items'][0]['review_url'])
  self.assertEqual(len(label_queue.listing(self.data,source='videos')['items']),1)
  self.assertEqual(len(label_queue.listing(self.data,source='detections')['items']),3)
 def test_invalid_labels_tampering_and_expired_backlog(self):
  key=f'{1:032x}';body=dict(id=key,label='made_up',request_id='a'*32)
  with self.assertRaises(ValueError):label_queue.label(self.data,body)
  path=self.root/'notifications/outbox'/key;(path/'native-object.png').write_bytes(b'tampered')
  with self.assertRaisesRegex(ValueError,'checksum'):label_queue.label(self.data,dict(body,label='bird'))
  (path/'delivery.json').write_text('{"state":"cancelled"}');self.assertEqual(label_queue.listing(self.data)['total'],2)
  with self.assertRaises(ValueError):label_queue.image_path(self.data,'../escape')


 def test_release_hides_old_detections_without_deleting_review_evidence(self):
  marker=self.root/'notifications/active-model-release.json'
  marker.write_text(json.dumps(dict(state='deployed',health_verified=True,version='new',deployed_epoch=2)))
  self.assertEqual([r['id'] for r in label_queue.detections(self.data)['items']],[f'{3:032x}'])
  self.assertTrue((self.root/'notifications/outbox'/f'{1:032x}'/'native-object.png').exists())
  # An old emailed review remains labelable even after leaving the fresh queue.
  self.assertTrue(label_queue.label(self.data,dict(id=f'{1:032x}',label='tree',request_id='a'*32))['saved'])

 def test_landscape_can_be_saved(self):
  result=label_queue.label(self.data,dict(id=f'{1:032x}',label='landscape',request_id='a'*32))
  self.assertEqual(result['label'],'landscape')
