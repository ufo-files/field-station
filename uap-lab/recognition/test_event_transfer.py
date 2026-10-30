import time,unittest
from pathlib import Path
from types import SimpleNamespace
from recognition_events import EventSink
class Transfer(unittest.TestCase):
 def sink(self):
  s=EventSink.__new__(EventSink);s.previous=dict(generation='run',last_sequence=10,analyzed_frames=11,generation_analyzed_frames=11);s.config_checked=0;s.model=None;s.frames=0;s.started=time.monotonic();s.monitor=SimpleNamespace(folder=Path('/tmp'),config={});s.lab=SimpleNamespace(DATA=Path('/tmp'),read=lambda *args: {});s.records=[];s.journal=SimpleNamespace(submit=s.records.append);return s
 def test_replay_prefix_does_not_regress_or_retrigger(self):
  s=self.sink();s.submit(dict(sequence=9),[],{},'run',{},dict(frames=9,proposals=0));self.assertEqual(s.records,[]);self.assertEqual(s.previous['last_sequence'],10)
 def test_transfer_requires_next_native_frame(self):
  s=self.sink()
  with self.assertRaises(ValueError):s.submit(dict(sequence=12),[],{},'run',{},dict(frames=12,proposals=0))
 def test_next_frame_uses_existing_event_journal(self):
  s=self.sink();s.submit(dict(sequence=11,pts_seconds=1,received_epoch=time.time()),[[1,2,3,4]],{},'run',dict(captured_frames=12),dict(frames=11,proposals=1));self.assertEqual(len(s.records),1);self.assertEqual(s.records[0][1],[[1,2,3,4]]);self.assertEqual(s.previous['generation_analyzed_frames'],12)
