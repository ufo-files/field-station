import json,os
from unittest.mock import patch
from test_detection_library import LibraryTests,listing
from object_omission import omit,omitted
import detection_library as library

class OmissionTests(LibraryTests):
 def setUp(self):
  super().setUp();self.env=patch.dict(os.environ,UAP_LAB_DATA=str(self.data));self.env.start();self.addCleanup(self.env.stop)
 def test_deletes_detection_pixels_and_retries_idempotently(self):
  key=f'{1:032x}';listing(self.data)
  result=omit(self.data,dict(id=key));self.assertTrue(result['deleted']);self.assertEqual(result['files_deleted'],2)
  self.assertFalse((self.root/'notifications/outbox'/key/'native-object.png').exists())
  self.assertNotIn(key,[r['id'] for r in listing(self.data)['items']]);self.assertEqual(omit(self.data,dict(id=key)),result)
  self.assertTrue((self.root/'notifications/outbox'/f'{2:032x}'/'native-object.png').exists())
 def test_reviewed_crop_deleted_and_stale_labels_cannot_restore_it(self):
  key=f'{1:032x}';library.label(self.data,dict(id=key,label='anomalous',request_id='a'*32))
  result=omit(self.data,dict(id=key));self.assertTrue(result['deleted'])
  folder=self.data/'email-reviews/examples'/key;self.assertFalse((folder/'native-object.png').exists());self.assertTrue(json.loads((folder/'review.json').read_text())['deleted'])
  response=library.label_batch(self.data,dict(items=[dict(id=key,label='anomalous',request_id='b'*32)]));self.assertTrue(response['results'][0]['discarded'])
  from email_training import store_review
  record=json.loads((folder/'review.json').read_text());record.update(message_id='late',source='station_web_review')
  with self.assertRaisesRegex(ValueError,'deleted'):store_review(self.data,record,self.crop)
 def test_shared_event_media_and_other_annotation_survive(self):
  from email_training import store_review
  key=f'{1:032x}';library.label(self.data,dict(id=key,label='anomalous',request_id='a'*32))
  record=json.loads((self.data/'email-reviews/examples'/key/'review.json').read_text());other='f'*32
  store_review(self.data,dict(record,sample_id=other,message_id='other'),self.crop)
  result=omit(self.data,dict(id=key));self.assertTrue(result['shared_media_retained'])
  self.assertTrue((self.root/'notifications/outbox'/key/'native-object.png').exists());self.assertTrue((self.data/'email-reviews/examples'/other/'native-object.png').exists())
  self.assertEqual(listing(self.data,'human_reviewed')['total'],1)
 def test_active_event_marks_media_for_retention_without_deleting_open_files(self):
  key=f'{1:032x}';(self.root/'notifications/outbox/producer-state.json').write_text(json.dumps(dict(groups=[dict(id=key)])))
  result=omit(self.data,dict(id=key));self.assertTrue(result['cleanup_pending']);self.assertTrue((self.root/'notifications/outbox'/key/'native-object.png').exists())
  self.assertTrue(json.loads((self.root/'notifications/outbox'/key/'label-queue-dismissed.json').read_text())['dismissed'])
 def test_unsafe_paths_fail_before_tombstone_or_delete(self):
  key=f'{1:032x}';folder=self.root/'notifications/outbox'/key;(folder/'linked.png').symlink_to(self.root/'notifications/outbox'/f'{2:032x}'/'native-object.png')
  with self.assertRaisesRegex(ValueError,'Unsafe'):omit(self.data,dict(id=key))
  self.assertFalse(omitted(self.data,key));self.assertTrue((folder/'native-object.png').exists())
  with self.assertRaises(ValueError):omit(self.data,dict(id='../other'))
 def test_video_omission_keeps_other_crops_and_deletes_last_source(self):
  key='d'*32;sample='e'*32;other='f'*32;folder=self.data/'videos'/key;folder.mkdir(parents=True)
  (folder/'video.json').write_text('{}');(folder/'annotations.json').write_text(json.dumps([dict(id=sample,image='one.png'),dict(id=other,image='two.png')]))
  for name in ['one.png','two.png','source']:(folder/name).write_bytes(self.crop)
  result=omit(self.data,dict(id='video:'+key+':'+sample));self.assertTrue(result['shared_media_retained']);self.assertFalse((folder/'one.png').exists());self.assertTrue((folder/'source').exists());self.assertTrue((folder/'two.png').exists())
  omit(self.data,dict(id='video:'+key+':'+other));self.assertFalse((folder/'two.png').exists());self.assertFalse((folder/'source').exists())

 def test_interrupted_unlink_is_retried_by_retention(self):
  from pathlib import Path
  from object_omission import retry_pending
  key=f'{1:032x}'
  with patch.object(Path,'unlink',side_effect=OSError('Temporary I/O failure')):
   with self.assertRaises(OSError):omit(self.data,dict(id=key))
  self.assertFalse(json.loads((self.data/'omitted-objects.json').read_text())['objects'][key]['complete'])
  self.assertTrue(retry_pending(self.data)[0]['deleted']);self.assertFalse((self.root/'notifications/outbox'/key/'object.png').exists())
