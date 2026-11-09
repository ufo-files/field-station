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

class TimingTailTests(unittest.TestCase):
 def fixture(self,p):
  from spool_events import atomic
  source=b'preserved encoded frames';e=dict(file='segment-1.mkv',bytes=len(source),sha256=hashlib.sha256(source).hexdigest(),start=1.,end=2.)
  (p/e['file']).write_bytes(source);(p/'closed.json').write_text('{}');(p/'segments-index.jsonl').write_text(json.dumps(e)+'\n')
  audit=dict(source=e,analyzed=False,frames=17,last_verified_pts=1.1,first_unavailable_pts=1.2,last_unavailable_pts=1.9)
  atomic(p/(e['file']+'.timing-unavailable.json'),audit)
  return e,audit
 def test_verified_closed_tail_preserves_original_and_marks_unanalyzed(self):
  from empty_segment import verified_timing_tail
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);e,a=self.fixture(p);self.assertEqual(verified_timing_tail(p,e),a);self.assertEqual((p/e['file']).read_bytes(),b'preserved encoded frames')
 def test_live_interior_or_modified_source_cannot_be_recovered(self):
  from empty_segment import verified_timing_tail
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);e,a=self.fixture(p);(p/'closed.json').unlink();self.assertIsNone(verified_timing_tail(p,e))
   self.fixture(p);(p/'segments-index.jsonl').write_text(json.dumps(e)+'\n'+json.dumps(dict(e,file='segment-2.mkv'))+'\n');self.assertIsNone(verified_timing_tail(p,e))
   self.fixture(p);(p/e['file']).write_bytes(b'changed');self.assertIsNone(verified_timing_tail(p,e))
 def test_invalid_missing_interval_is_not_accepted(self):
  from empty_segment import verified_timing_tail
  from spool_events import atomic
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);e,a=self.fixture(p);a['first_unavailable_pts']=1.0;atomic(p/(e['file']+'.timing-unavailable.json'),a);self.assertIsNone(verified_timing_tail(p,e))
