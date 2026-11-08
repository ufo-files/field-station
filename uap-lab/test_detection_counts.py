import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from detection_library import listing

class DetectionCountsTests(unittest.TestCase):
 def test_ready_arrivals_do_not_mark_partial_library_counts_complete(self):
  with tempfile.TemporaryDirectory() as tmp:
   data=Path(tmp)/'uap-lab';data.mkdir()
   with patch('detection_library.refresh',return_value=(None,True,None)),patch('recognition.recognition_alerts.recent_detections',return_value=([],True)):
    result=listing(data,view='needs_review')
   self.assertTrue(result['ready']);self.assertFalse(result['indexing']);self.assertTrue(result['counts_indexing'])

 def test_complete_cached_counts_remain_available_during_refresh(self):
  for stamp in (-1,123):
   with self.subTest(stamp=stamp),tempfile.TemporaryDirectory() as tmp:
    data=Path(tmp)/'uap-lab';data.mkdir()
    with patch('detection_library.refresh',return_value=((stamp,[]),True,None)),patch('recognition.recognition_alerts.recent_detections',return_value=([],True)):
     result=listing(data,view='needs_review')
    self.assertFalse(result['counts_indexing'])

 def test_partial_cached_counts_are_not_ready(self):
  with tempfile.TemporaryDirectory() as tmp:
   data=Path(tmp)/'uap-lab';data.mkdir()
   with patch('detection_library.refresh',return_value=((0,[]),True,None)),patch('recognition.recognition_alerts.recent_detections',return_value=([],True)):
    result=listing(data,view='needs_review')
   self.assertTrue(result['counts_indexing'])

 def test_complete_arrivals_avoid_archived_event_scan(self):
  from detection_library import collect
  with tempfile.TemporaryDirectory() as tmp:
   data=Path(tmp)/'uap-lab';data.mkdir()
   row=dict(id='a'*32,kind='detection',created=123,label='anomalous',human_reviewed=False,model_label='anomalous')
   with patch('recognition.recognition_alerts.recent_detections',return_value=([row],True)),patch('queue_index.ordered',side_effect=AssertionError('Archived events must not be scanned')),patch('labeled_frames.listing',return_value={'items':[]}):
    self.assertEqual(collect(data),[row])
