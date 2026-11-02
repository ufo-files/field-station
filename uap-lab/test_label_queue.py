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
 def test_retired_structures_cannot_be_selected_or_saved(self):
  choices=set(label_queue.listing(self.data)['labels'])
  self.assertFalse({'house','antenna','telephone_pole','background'}&choices)
  self.assertTrue({'vehicle','cloud','bird','star'}<=choices)
  for category in ('house','antenna','telephone_pole','building/structure','tree','landscape','mountain'):
   with self.subTest(category=category),self.assertRaises(ValueError):
    label_queue.label(self.data,dict(id=f'{1:032x}',label=category,request_id='a'*32))
  self.assertTrue(label_queue.label(self.data,dict(id=f'{1:032x}',label='vehicle',request_id='a'*32))['saved'])
 def test_mountain_is_retired(self):
  with self.assertRaises(ValueError):label_queue.label(self.data,dict(id=f'{1:032x}',label='mountain',request_id='a'*32))
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
 def test_clear_backlog_links_frames_and_videos_preserves_reviews(self):
  reviewed=f'{3:032x}';label_queue.label(self.data,dict(id=reviewed,label='bird',request_id='a'*32))
  delivery=self.root/'notifications/outbox'/f'{1:032x}'/'delivery.json';delivery.write_text('{"state":"accepted_by_mail"}')
  for i in (10,11):
   p=self.data/'videos'/f'{i:032x}';p.mkdir(parents=True)
   (p/'video.json').write_text(json.dumps(dict(id=p.name,sha256=str(i),created=0)))
   (p/'source').write_bytes(b'original')
   if i==11:(p/'annotations.json').write_text('[{"label":"bird"}]')
  before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  result=label_queue.clear_backlog(self.data)
  self.assertEqual(result['frames_cleared'],2);self.assertEqual(result['videos_cleared'],1);self.assertEqual(result['protected'],1)
  remaining=label_queue.listing(self.data)
  self.assertEqual([r['id'] for r in remaining['items']],[f'{11:032x}'])
  self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
  again=label_queue.clear_backlog(self.data);self.assertEqual(again['frames_cleared'],0);self.assertEqual(again['videos_cleared'],0)
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
  self.assertTrue(label_queue.label(self.data,dict(id=f'{1:032x}',label='bird',request_id='a'*32))['saved'])

 def test_landscape_is_retired(self):
  with self.assertRaises(ValueError):label_queue.label(self.data,dict(id=f'{1:032x}',label='landscape',request_id='a'*32))

 def test_new_model_does_not_hide_candidates_younger_than_48_hours(self):
  import time
  now=time.time();key=f'{1:032x}';path=self.root/'notifications/outbox'/key/'event.json'
  event=json.loads(path.read_text());event['created_epoch']=now-3600;path.write_text(json.dumps(event))
  marker=self.root/'notifications/active-model-release.json';marker.write_text(json.dumps(dict(state='deployed',health_verified=True,version='new',deployed_epoch=now)))
  self.assertIn(key,[r['id'] for r in label_queue.detections(self.data)['items']])
  marker.write_text(json.dumps(dict(state='deployed',health_verified=True,version='new',deployed_epoch=now,clear_candidate_backlog=True)))
  self.assertNotIn(key,[r['id'] for r in label_queue.detections(self.data)['items']])

 def test_recently_emailed_candidate_sorts_first_even_with_small_random_id(self):
  import os,time
  first=self.root/'notifications/outbox'/f'{1:032x}'
  (first/'delivery.json').write_text(json.dumps({'state':'accepted_by_mail'}))
  future=time.time()+5;os.utime(first,(future,future))
  result=label_queue.detections(self.data,limit=1)
  self.assertEqual(result['items'][0]['id'],f'{1:032x}')
  second=label_queue.detections(self.data,before=result['next_cursor'],limit=1)
  self.assertEqual(second['items'][0]['id'],f'{3:032x}')

 def test_reconcile_reads_saved_labels_even_when_manifest_is_stale(self):
  key=f'{3:032x}';body=dict(id=key,label='cloud',request_id='a'*32)
  label_queue.label(self.data,body)
  item=dict(id=key,kind='detection')
  self.assertEqual(label_queue.review_status(self.data,[item])['reviewed'],[item])
  self.assertEqual(label_queue.review_status(self.data,[item])['confirmed'],[dict(item,label='cloud')])
  path=self.data/'email-reviews/examples'/key/'review.json';row=json.loads(path.read_text());row['deleted']=True;path.write_text(json.dumps(row))
  self.assertEqual(label_queue.review_status(self.data,[item])['reviewed'],[])
 def test_reconcile_quick_video_review_and_undo(self):
  key='a'*32;target=self.data/'videos'/key;target.mkdir(parents=True)
  (target/'video.json').write_text('{"sha256":"video"}')
  (target/'quick-frame-review.json').write_text('{"annotation_id":"saved"}')
  (target/'annotations.json').write_text('[{"id":"saved","label":"cloud"}]')
  item=dict(id=key,kind='video')
  self.assertEqual(label_queue.review_status(self.data,[item])['reviewed'],[item])
  self.assertEqual(label_queue.review_status(self.data,[item])['confirmed'],[dict(item,label='cloud')])
  (target/'annotations.json').write_text('[]')
  self.assertEqual(label_queue.review_status(self.data,[item])['reviewed'],[])

 def test_original_receipt_acknowledges_retry_after_later_label_deletion(self):
  key=f'{3:032x}';body=dict(id=key,label='cloud',request_id='b'*32)
  label_queue.label(self.data,body)
  path=self.data/'email-reviews/examples'/key/'review.json';row=json.loads(path.read_text());row['deleted']=True;path.write_text(json.dumps(row))
  item=dict(id=key,kind='detection',request_id=body['request_id'],pending_label='cloud')
  status=label_queue.review_status(self.data,[item])
  self.assertEqual(status['confirmed'],[])
  self.assertEqual(status['acknowledged'],[dict(id=key,kind='detection',request_id=body['request_id'])])
  self.assertTrue(json.loads(path.read_text())['deleted'])
  item['pending_label']='bird';self.assertEqual(label_queue.review_status(self.data,[item])['acknowledged'],[])

 def test_reviewed_page_renews_video_source_lease(self):
  key='a'*32
  label_queue.review_status(self.data,[dict(id=key,kind='video')])
  leases=json.loads((self.data/'review-leases.json').read_text())
  self.assertGreater(leases[key],label_queue.time.time()+800)

 def test_archived_unreviewed_video_closes_card_without_acknowledging_save(self):
  key='a'*32;folder=self.data/'videos'/key;folder.mkdir(parents=True)
  (folder/'video.json').write_text('{"media_expired":true}')
  item=dict(id=key,kind='video',request_id='b'*32,pending_label='cloud')
  status=label_queue.review_status(self.data,[item])
  self.assertEqual(status['reviewed'],[item]);self.assertEqual(status['confirmed'],[]);self.assertEqual(status['acknowledged'],[])
