import hashlib,json,tempfile,unittest
from pathlib import Path
from empty_segment import closed_empty_segment,record_empty_segment
class EmptySegmentTests(unittest.TestCase):
 def test_only_closed_hash_verified_empty_capture_is_recoverable(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);e=dict(file='segment-1.mkv',bytes=0,sha256=hashlib.sha256(b'').hexdigest());(p/e['file']).touch()
   self.assertFalse(closed_empty_segment(p,e));(p/'closed.json').write_text('{}');self.assertTrue(closed_empty_segment(p,e))
   record=record_empty_segment(p,e);self.assertFalse(json.loads(record.read_text())['analyzed']);self.assertTrue((p/e['file']).exists())
   (p/e['file']).write_bytes(b'valid video');self.assertFalse(closed_empty_segment(p,e))
 def test_wrong_hash_missing_file_and_path_escape_are_not_skipped(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'closed.json').write_text('{}');(p/'empty.mkv').touch()
   for e in [dict(file='empty.mkv',bytes=0,sha256='wrong'),dict(file='missing.mkv',bytes=0,sha256=hashlib.sha256(b'').hexdigest()),dict(file='../empty.mkv',bytes=0,sha256=hashlib.sha256(b'').hexdigest())]:self.assertFalse(closed_empty_segment(p,e))
