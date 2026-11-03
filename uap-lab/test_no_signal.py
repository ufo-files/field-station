import unittest
from pathlib import Path
import cv2
import numpy as np
from no_signal import NoSignalDetector
class NoSignalTests(unittest.TestCase):
 def setUp(self):
  self.detector=NoSignalDetector();self.raw=Path(__file__).with_name('elgato-no-signal-reference.jpg').read_bytes()
 def encoded(self,image,quality=80):return cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,quality])[1].tobytes()
 def test_real_slate_and_scaled_jpeg(self):
  self.assertTrue(self.detector.matches(self.raw))
  frame=cv2.imdecode(np.frombuffer(self.raw,np.uint8),cv2.IMREAD_COLOR)
  self.assertTrue(self.detector.matches(self.encoded(cv2.resize(frame,(1920,1080)),55)))
 def test_dark_sky_stars_noise_and_missing_lettering_do_not_match(self):
  sky=np.zeros((720,1280,3),np.uint8)
  self.assertFalse(self.detector.matches(self.encoded(sky)))
  for x,y in [(640,360),(570,450),(800,400)]:cv2.circle(sky,(x,y),3,(255,255,255),-1)
  self.assertFalse(self.detector.matches(self.encoded(sky)))
  self.assertFalse(self.detector.matches(self.encoded(np.random.default_rng(1).integers(0,256,sky.shape,dtype=np.uint8))))
  frame=cv2.imdecode(np.frombuffer(self.raw,np.uint8),cv2.IMREAD_COLOR);frame[440:476]=0
  self.assertFalse(self.detector.matches(self.encoded(frame)))
  self.assertFalse(self.detector.matches(b'broken'))
