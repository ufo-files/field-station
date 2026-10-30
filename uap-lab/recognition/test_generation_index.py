import tempfile,unittest
from pathlib import Path
from recognition_service import read_index
class GenerationIndexTests(unittest.TestCase):
 def test_new_generation_waits_for_first_segment(self):
  with tempfile.TemporaryDirectory() as tmp:self.assertEqual(read_index(Path(tmp),0),(b'',0,b''))
 def test_missing_existing_index_fails_closed(self):
  with tempfile.TemporaryDirectory() as tmp:
   with self.assertRaises(FileNotFoundError):read_index(Path(tmp),100)
 def test_partial_append_is_not_claimed_complete(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'segments-index.jsonl').write_bytes(b'{"file":"a"}\n{"file":')
   line,offset,nextline=read_index(root,0);self.assertTrue(line.endswith(b'\n'));self.assertFalse(nextline.endswith(b'\n'));self.assertEqual(offset,len(line))
