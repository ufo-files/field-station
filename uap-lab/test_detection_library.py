import json,time
from unittest.mock import patch
from test_label_queue import QueueTests
import detection_library as library

class LibraryTests(QueueTests):
 def setUp(self):
  super().setUp();library.invalidate()
  for p in (self.root/'notifications/outbox').glob('*/event.json'):
   e=json.loads(p.read_text());e['classification']='anomalous' if e['sequence']==1 else 'not_anomalous';e['review_only']=e['sequence']!=1;p.write_text(json.dumps(e))
  self.gallery=patch('labeled_frames.listing',return_value={'items':[]});self.gallery_mock=self.gallery.start()
 def tearDown(self):self.gallery.stop();library.invalidate();super().tearDown()
 def test_model_labels_are_not_reviews_or_training(self):
  self.assertEqual(library.listing(self.data)['counts'],dict(all=3,anomalous=1,not_anomalous=2,needs_review=3,human_reviewed=0))
  self.assertFalse((self.data/'email-reviews').exists())
 def test_negative_suppression_is_not_review_dismissal(self):
  (self.root/'notifications/outbox'/f'{2:032x}'/'delivery.json').write_text('{"state":"suppressed"}')
  self.assertEqual(library.listing(self.data,'not_anomalous')['total'],2)
 def test_human_override_keeps_model_label_and_moves_views(self):
  import label_queue
  key=f'{1:032x}';library.label(self.data,dict(id=key,label='not_anomalous',request_id='a'*32))
  record=json.loads((self.data/'email-reviews/examples'/key/'review.json').read_text())
  self.assertTrue(record['human_confirmed'])
  self.gallery_mock.return_value={'items':[dict(kind='review',video_id=key,created=1,annotation=dict(id=key,label='not_anomalous'),image_url='/crop')]}
  library.invalidate();row=library.listing(self.data,'human_reviewed')['items'][0]
  self.assertEqual(row['model_label'],'anomalous');self.assertEqual(row['label'],'not_anomalous')
  self.assertEqual(library.listing(self.data,'needs_review')['total'],2)
  library.label(self.data,dict(id=key,label='anomalous',request_id='b'*32))
  self.assertEqual(json.loads((self.data/'email-reviews/examples'/key/'review.json').read_text())['label'],'anomalous')
 def test_paging_survives_newer_review(self):
  page=library.listing(self.data,limit=1);second=library.listing(self.data,before=page['next_cursor'],limit=1)
  self.assertNotEqual(page['items'][0]['id'],second['items'][0]['id'])
