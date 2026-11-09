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
 def test_motion_blurred_silhouette_remains_a_candidate(self):
  base=np.full((1080,1920),160,np.uint8)
  for blur in (0,1,2,3,4):
   with self.subTest(blur=blur):
    detector=NativeMotion();detector.update(base,0)
    frame=base.copy();cv2.ellipse(frame,(800,400),(25,10),20,0,360,60,-1)
    if blur:frame=cv2.GaussianBlur(frame,(0,0),blur)
    boxes,_=detector.update(frame,1/60)
    self.assertTrue(any(x<825 and x+w>775 and y<415 and y+h>385 for x,y,w,h in boxes))
 def test_broad_moving_cloud_has_no_compact_candidates(self):
  yy,xx=np.mgrid[:360,:640]
  detector=NativeMotion()
  for i in range(30):
   cloud=120+60*np.exp(-((xx-240-i*2)**2+(yy-180)**2)/(2*65**2))
   boxes,_=detector.update(cloud.astype(np.uint8),i/60)
   self.assertEqual(boxes,[])
 def test_close_large_silhouette_is_not_discarded_by_size(self):
  base=np.full((1080,1920),160,np.uint8)
  detector=NativeMotion();detector.update(base,0)
  frame=base.copy();cv2.ellipse(frame,(800,400),(230,110),20,0,360,60,-1)
  frame=cv2.GaussianBlur(frame,(0,0),2)
  boxes,_=detector.update(frame,1/60)
  self.assertTrue(any(w>1920*.15 or h>1080*.15 for x,y,w,h in boxes))
 def test_uniform_exposure_change_does_not_create_objects(self):
  detector=NativeMotion()
  for i in range(30):
   boxes,_=detector.update(np.full((360,640),80+i*3,np.uint8),i/60)
   self.assertEqual(boxes,[])
 def test_timestamp_gap_resets_background(self):
  d=NativeMotion();base=np.zeros((120,160),np.uint8);d.update(base,0);_,status=d.update(base,1);self.assertTrue(status['warming'])
