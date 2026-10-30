import unittest
import cv2,numpy as np
from motion_overlay import MotionOverlay

class MotionOverlayTests(unittest.TestCase):
    def test_static_scene_is_empty_and_movement_is_display_only(self):
        tracker=MotionOverlay();image=np.full((240,320,3),100,np.uint8)
        for i in range(10):self.assertEqual(tracker.update(image,i*.2),[])
        moved=image.copy();cv2.rectangle(moved,(40,60),(50,70),(220,220,220),-1)
        objects=tracker.update(moved,2)
        self.assertTrue(objects)
        self.assertTrue(all(o['label']=='motion' and o['source']=='display_only' for o in objects))
        self.assertTrue(all('confirmed' not in o and 'score' not in o for o in objects))
    def test_duplicate_frame_does_not_advance_background_or_tracks(self):
        tracker=MotionOverlay();image=np.zeros((100,100,3),np.uint8)
        tracker.update(image,1);tracker.update(image,1);self.assertEqual(tracker.frames,1)
    def test_camera_gap_clears_stale_motion(self):
        tracker=MotionOverlay();image=np.zeros((100,100,3),np.uint8)
        for i in range(10):tracker.update(image,i*.2)
        image[40:50,40:50]=255;self.assertTrue(tracker.update(image,2))
        self.assertEqual(tracker.update(image,5),[])
    def test_global_lighting_change_is_not_covered_in_motion_boxes(self):
        tracker=MotionOverlay()
        for i in range(10):tracker.update(np.zeros((100,100,3),np.uint8),i*.2)
        self.assertEqual(tracker.update(np.full((100,100,3),255,np.uint8),2),[])

if __name__=='__main__':unittest.main()
