import json,tempfile,unittest
from pathlib import Path
from generation_recovery import recover_missing_generation
class RecoveryTests(unittest.TestCase):
 def test_existing_cursor_is_untouched(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'run-old').mkdir();self.assertIsNone(recover_missing_generation(root,{'generation':'run-old'},None))
 def test_resumes_earliest_available_source_preserving_totals(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for name,epoch in [('run-a',15),('run-b',30)]:
    folder=root/name;folder.mkdir();(folder/'present.mkv').touch()
    (folder/'segments-index.jsonl').write_text(json.dumps(dict(file='deleted.mkv',start_epoch=epoch-1,start=0))+'\n'+json.dumps(dict(file='present.mkv',start_epoch=epoch,start=1))+'\n')
   old=dict(generation='run-old',frames=99,last_sequence=7,tracks={'a':1},model='new')
   recovered=recover_missing_generation(root,old,10)
   self.assertEqual(recovered['generation'],'run-a');self.assertGreater(recovered['offset'],0);self.assertEqual(recovered['frames'],99);self.assertEqual(recovered['tracks'],{});self.assertIsNone(recovered['last_sequence']);self.assertEqual(old['generation'],'run-old');self.assertEqual(recovered['generation_recoveries'][0]['reason'],'source_generation_missing')
 def test_waits_without_fabricating_capture_directory(self):
  with tempfile.TemporaryDirectory() as tmp:
   with self.assertRaises(RuntimeError):recover_missing_generation(Path(tmp),{'generation':'run-old'},10)
   self.assertFalse((Path(tmp)/'run-old').exists())
 def test_unknown_timestamp_does_not_skip_data(self):
  with tempfile.TemporaryDirectory() as tmp:
   with self.assertRaises(RuntimeError):recover_missing_generation(Path(tmp),{'generation':'run-old'},None)
if __name__=='__main__':unittest.main()
