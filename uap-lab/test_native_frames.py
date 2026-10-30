import tempfile,threading,json,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from native_frames import NativeFrames
class ReaderTests(unittest.TestCase):
 def run_frames(self,sequences):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name);folder=root/'run-abcdef';folder.mkdir();(folder/'segment-000000000.mkv').touch();(folder/'segments.csv').write_text('segment-000000000.mkv,0,0.05\n')
  rows=[dict(sequence=n,pts_seconds=i/60,received_epoch=100+i/60) for i,n in enumerate(sequences)];(folder/'frame-times-000000000.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
  class Capture:
   def __init__(self,*a):self.i=0
   def read(self):
    if self.i==len(sequences):return False,None
    self.i+=1;return True,np.full((4,4),self.i,np.uint8)
   def release(self):pass
  return root,Capture
 def test_all_native_frames_and_timestamps_in_order(self):
  root,cap=self.run_frames([10,11,12]);reader=NativeFrames(root);stop=threading.Event()
  with patch('native_frames.cv2.VideoCapture',cap):
   gen=reader.threaded_frames(stop);rows=[next(gen) for _ in range(3)];gen.close()
  self.assertEqual([r[1]['sequence'] for r in rows],[10,11,12]);self.assertEqual(rows[-1][2]['decoded_frames'],3);self.assertEqual(rows[-1][2]['missing_frames'],0)
 def test_missing_frames_are_counted(self):
  root,cap=self.run_frames([10,12,13]);reader=NativeFrames(root);stop=threading.Event()
  with patch('native_frames.cv2.VideoCapture',cap):
   gen=reader.threaded_frames(stop);rows=[next(gen) for _ in range(3)];gen.close()
  self.assertEqual(rows[-1][2]['missing_frames'],1)
 def test_duplicate_frames_fail_instead_of_inflating_count(self):
  root,cap=self.run_frames([10,10,11]);reader=NativeFrames(root);stop=threading.Event()
  with patch('native_frames.cv2.VideoCapture',cap):
   gen=reader.threaded_frames(stop);next(gen)
   with self.assertRaises(ValueError):next(gen)
   gen.close()
 def test_checkpoint_resumes_without_skipping_or_recounting_saved_frames(self):
  root,cap=self.run_frames([10,11,12]);reader=NativeFrames(root,True,dict(generation='run-abcdef',last_sequence=10));stop=threading.Event()
  with patch('native_frames.cv2.VideoCapture',cap):
   gen=reader.threaded_frames(stop);rows=[next(gen) for _ in range(2)];gen.close()
  self.assertEqual([r[1]['sequence'] for r in rows],[11,12]);self.assertEqual(rows[-1][2]['decoded_frames'],2);self.assertEqual(rows[-1][2]['missing_frames'],0)
 def test_decoding_ahead_of_consumer_does_not_skip_tail_after_restart(self):
  import time
  root,cap=self.run_frames([0,1,2]);old=root/'run-abcdef';(old/'generation.json').write_text(json.dumps(dict(created_epoch=1)));(old/'closed.json').write_text('{}');(old/'segments-index.jsonl').write_text(json.dumps(dict(file='segment-000000000.mkv',start=0,end=.05))+'\n')
  newer=root/'run-new';newer.mkdir();(newer/'generation.json').write_text(json.dumps(dict(created_epoch=2)));(newer/'segment-000000000.mkv').touch();(newer/'segments-index.jsonl').write_text((old/'segments-index.jsonl').read_text());(newer/'frame-times-000000000.jsonl').write_text((old/'frame-times-000000000.jsonl').read_text())
  with patch('native_frames.cv2.VideoCapture',cap):
   reader=NativeFrames(root);stop=threading.Event();gen=reader.threaded_frames(stop);first=next(gen);deadline=time.monotonic()+2
   while not (old/'decode-complete.json').exists() and time.monotonic()<deadline:time.sleep(.01)
   self.assertTrue((old/'decode-complete.json').exists());self.assertFalse((old/'analysis-complete.json').exists());gen.close()
   recovered=NativeFrames(root,checkpoint=dict(generation=old.name,last_sequence=0));gen=recovered.threaded_frames(threading.Event());rows=[next(gen),next(gen)];gen.close()
  self.assertEqual([r[1]['sequence'] for r in rows],[1,2]);self.assertTrue(all(r[2]['generation']==old.name for r in rows))
