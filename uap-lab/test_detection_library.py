import json,time
from unittest.mock import patch
from test_label_queue import QueueTests
import detection_library as library

def listing(*a,**kw):return library.listing(*a,**kw,wait=True)

class LibraryTests(QueueTests):
 def setUp(self):
  super().setUp();library.invalidate()
  for p in (self.root/'notifications/outbox').glob('*/event.json'):
   e=json.loads(p.read_text());e['classification']='anomalous' if e['sequence']==1 else 'not_anomalous';e['review_only']=e['sequence']!=1;p.write_text(json.dumps(e))
  self.gallery=patch('labeled_frames.listing',return_value={'items':[]});self.gallery_mock=self.gallery.start()
 def tearDown(self):self.gallery.stop();library.invalidate();super().tearDown()
 def test_batch_persists_positive_and_negative_and_retries_without_duplication(self):
  from email_review import event_reviews,annotation_revision
  items=[dict(id=f'{i:032x}',label='anomalous' if i==1 else 'not_anomalous',request_id=f'{i+20:032x}') for i in (1,2)]
  result=library.label_batch(self.data,dict(items=items));self.assertTrue(all(r['saved'] for r in result['results']))
  manifest=json.loads((self.data/'email-reviews/training-manifest.json').read_text());self.assertEqual(len(manifest['examples']),2)
  for item in items:self.assertEqual(event_reviews(self.data,item['id'])[0]['label'],item['label'])
  completed=json.loads((self.root/'notifications/outbox'/items[0]['id']/'review-completion.json').read_text())
  self.assertEqual(completed['annotation_revision'],annotation_revision(self.data,items[0]['id']))
  before=(self.data/'email-reviews/training-manifest.json').read_bytes();retry=library.label_batch(self.data,dict(items=items))
  self.assertTrue(all(r['saved'] for r in retry['results']));self.assertEqual(before,(self.data/'email-reviews/training-manifest.json').read_bytes())
 def test_batch_commits_good_items_and_preserves_failed_item_for_retry(self):
  items=[dict(id=f'{i:032x}',label='not_anomalous',request_id=f'{i+20:032x}') for i in (1,2)]
  (self.root/'notifications/outbox'/items[1]['id']/'native-object.png').write_bytes(b'corrupt')
  result=library.label_batch(self.data,dict(items=items));self.assertTrue(result['results'][0]['saved']);self.assertFalse(result['results'][1]['saved'])
  self.assertEqual(len(json.loads((self.data/'email-reviews/training-manifest.json').read_text())['examples']),1)
 def test_model_labels_are_not_reviews_or_training(self):
  self.assertEqual(listing(self.data)['counts'],dict(all=3,anomalous=1,not_anomalous=2,needs_review=3,human_reviewed=0,human_reviewed_anomalous=0))
  self.assertFalse((self.data/'email-reviews').exists())
 def test_negative_suppression_is_not_review_dismissal(self):
  (self.root/'notifications/outbox'/f'{2:032x}'/'delivery.json').write_text('{"state":"suppressed"}')
  self.assertEqual(listing(self.data,'not_anomalous')['total'],2)
 def test_human_override_keeps_model_label_and_moves_views(self):
  import label_queue
  key=f'{1:032x}';library.label(self.data,dict(id=key,label='not_anomalous',request_id='a'*32))
  record=json.loads((self.data/'email-reviews/examples'/key/'review.json').read_text())
  self.assertTrue(record['human_confirmed'])
  self.gallery_mock.return_value={'items':[dict(kind='review',video_id=key,created=1,annotation=dict(id=key,label='not_anomalous'),image_url='/crop')]}
  library.invalidate();row=listing(self.data,'human_reviewed')['items'][0]
  self.assertEqual(row['model_label'],'anomalous');self.assertEqual(row['label'],'not_anomalous')
  self.assertEqual(listing(self.data,'needs_review')['total'],2)
  library.label(self.data,dict(id=key,label='anomalous',request_id='b'*32))
  self.assertEqual(json.loads((self.data/'email-reviews/examples'/key/'review.json').read_text())['label'],'anomalous')
 def test_paging_survives_newer_review(self):
  page=listing(self.data,limit=1);second=listing(self.data,before=page['next_cursor'],limit=1)
  self.assertNotEqual(page['items'][0]['id'],second['items'][0]['id'])

 def test_human_anomalous_filter_requires_both_conditions(self):
  key=f'{1:032x}'
  self.assertEqual(listing(self.data,'human_reviewed_anomalous')['total'],0)
  library.label(self.data,dict(id=key,label='anomalous',request_id='a'*32))
  self.gallery_mock.return_value={'items':[dict(kind='review',video_id=key,created=1,annotation=dict(id=key,label='anomalous'),image_url='/crop')]}
  library.invalidate();page=listing(self.data,'human_reviewed_anomalous')
  self.assertEqual(page['total'],1);self.assertEqual(page['items'][0]['id'],key)
  library.label(self.data,dict(id=key,label='not_anomalous',request_id='b'*32))
  self.assertEqual(listing(self.data,'human_reviewed_anomalous')['total'],0)
  self.assertEqual(listing(self.data,'human_reviewed')['total'],1)

 def test_external_review_overrides_stale_index_without_waiting_for_refresh(self):
  import time
  from email_training import store_review
  import hashlib
  key=f'{1:032x}';listing(self.data)
  store_review(self.data,dict(event_id=key,sample_id='f'*32,label='not_anomalous',human_confirmed=True,source='station_web_review',message_id='external',reviewed_epoch=time.time(),native_crop_sha256=hashlib.sha256(self.crop).hexdigest()),self.crop)
  page=listing(self.data,'needs_review');self.assertNotIn(key,[r['id'] for r in page['items']])
  reviewed=listing(self.data,'human_reviewed')['items'];self.assertEqual(len(reviewed),1);self.assertEqual(reviewed[0]['sample_id'],'f'*32)
 def test_clear_includes_old_model_and_filters_warm_cache_preserving_reviews(self):
  import label_queue
  key=f'{1:032x}'
  library.label(self.data,dict(id=key,label='not_anomalous',request_id='c'*32))
  (self.root/'notifications/active-model-release.json').write_text(json.dumps(dict(state='deployed',health_verified=True,version='new-model',deployed_epoch=10,clear_candidate_backlog=True)))
  self.assertEqual(label_queue.detections(self.data)['items'],[])
  self.assertEqual(listing(self.data,'needs_review')['total'],2)
  result=label_queue.clear_backlog(self.data,cutoff=2.5)
  self.assertEqual(result['frames_cleared'],1)
  self.assertTrue(json.loads((self.root/'notifications/outbox'/f'{2:032x}'/'label-queue-dismissed.json').read_text())['dismissed'])
  self.assertEqual([r['id'] for r in listing(self.data,'needs_review')['items']],[f'{3:032x}'])
  self.assertEqual(listing(self.data,'human_reviewed')['total'],1)
  # Simulate a background index publishing stale pre-clear objects again.
  library.invalidate()
  self.assertEqual([r['id'] for r in listing(self.data,'needs_review')['items']],[f'{3:032x}'])
  label_queue.clear_backlog(self.data,cutoff=10)
  self.assertEqual(listing(self.data,'needs_review')['total'],0)
  self.assertEqual(listing(self.data,'human_reviewed')['total'],1)
  self.assertEqual(json.loads((self.data/'email-reviews/examples'/key/'review.json').read_text())['label'],'not_anomalous')
 def test_clear_cutoff_does_not_regress_on_older_repair(self):
  import label_queue
  label_queue.clear_backlog(self.data,cutoff=10)
  label_queue.clear_backlog(self.data,cutoff=2)
  self.assertEqual(json.loads((self.data/'review-queue-cleared.json').read_text())['cutoff_epoch'],10)
