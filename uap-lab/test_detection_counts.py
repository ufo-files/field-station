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
