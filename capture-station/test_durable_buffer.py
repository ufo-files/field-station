import tempfile,threading,unittest,json
from pathlib import Path
from unittest.mock import patch
from rolling_buffer import RollingBuffer
class DurableTests(unittest.TestCase):
 def test_rotation_and_restart_never_delete_unacknowledged_evidence(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'CAPTURE_DURABLE_SPOOL':'1'}):
   root=Path(tmp);stop=threading.Event();stop.set();buffer=RollingBuffer(root,stop,keep_seconds=1,root=root/'spool');run=buffer.new_run()
   for i in range(4):(run/f'segment-{i:09d}.mkv').write_bytes(b'evidence')
   (run/'segments.csv').write_text(''.join(f'segment-{i:09d}.mkv,{i},{i+1}\n' for i in range(4)));buffer.ingest()
   self.assertEqual(len(list(run.glob('*.mkv'))),4);self.assertEqual(len((run/'segments-index.jsonl').read_text().splitlines()),4)
   buffer.new_run();self.assertTrue((run/'segment-000000000.mkv').exists());self.assertTrue((run/'closed.json').exists())
 def test_append_list_ignores_partial_rows_and_never_reindexes_old_segments(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'CAPTURE_DURABLE_SPOOL':'1'}):
   root=Path(tmp);stop=threading.Event();stop.set();buffer=RollingBuffer(root,stop,root=root/'spool');run=buffer.new_run()
   for i in range(2):(run/f'segment-{i:09d}.mkv').write_bytes(b'evidence')
   listing=run/'segments.csv';listing.write_text('segment-000000000.mkv,0,1\nsegment-000000001.mkv,1,');buffer.ingest();self.assertEqual(len(buffer.segments),1)
   with listing.open('a') as out:out.write('2\n')
   buffer.ingest();buffer.ingest();self.assertEqual(len((run/'segments-index.jsonl').read_text().splitlines()),2)
