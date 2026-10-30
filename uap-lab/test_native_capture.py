import tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from native_capture import NativeCapture
class RecoveryTests(unittest.TestCase):
 def test_decoder_retry_resumes_after_last_analyzed_frame(self):
  with tempfile.TemporaryDirectory() as tmp:
   stop=threading.Event();monitor=SimpleNamespace(stop_event=stop,folder=Path(tmp),state={},config={'provisional_enabled':False});engine=NativeCapture(monitor);checkpoints=[]
   class Reader:
    def __init__(self,*args,checkpoint=None,**kwargs):self.checkpoint=checkpoint or {};checkpoints.append(self.checkpoint.copy())
    def threaded_frames(self,stop):
     start=self.checkpoint.get('last_sequence',-1)+1
     for seq in range(start,8):
      if len(checkpoints)==1 and seq==4:raise ValueError('Decoder interrupted')
      if seq==7:stop.set()
      yield np.zeros((20,20),np.uint8),dict(sequence=seq,pts_seconds=seq/60,received_epoch=time.time()),dict(generation='run-abcdef',decode_errors=0,timestamp_errors=0,backlog_frames=0,backlog_seconds=0)
   with patch('native_capture.NativeFrames',Reader):engine.analyze()
   self.assertEqual(checkpoints[1]['last_sequence'],3);self.assertEqual(engine.status['analyzed_frames'],8);self.assertEqual(engine.status['missing_frames'],0);self.assertEqual(engine.status['failures'],1)
