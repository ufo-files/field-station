import unittest
import cv2,numpy as np
from native_motion import NativeMotion
class MotionTests(unittest.TestCase):
 def test_single_frame_target_is_preserved_as_candidate(self):
  d=NativeMotion();base=np.full((120,160),100,np.uint8);d.update(base,0)
  frame=base.copy();cv2.rectangle(frame,(60,40),(68,48),30,-1)
  boxes,status=d.update(frame,1/60);self.assertTrue(any(x<=64<=x+w and y<=44<=y+h for x,y,w,h in boxes));self.assertFalse(status['warming'])
 def test_smooth_moving_cloud_gradient_is_not_compact_target(self):
  d=NativeMotion();base=np.tile(np.linspace(50,150,160,dtype=np.uint8),(120,1))
  for i in range(20):
   boxes,_=d.update(np.clip(base.astype(int)+i,0,255).astype(np.uint8),i/60);self.assertEqual(boxes,[])
 def test_timestamp_gap_resets_background(self):
  d=NativeMotion();base=np.zeros((120,160),np.uint8);d.update(base,0);_,status=d.update(base,1);self.assertTrue(status['warming'])
