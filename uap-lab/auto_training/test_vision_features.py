import unittest
try:
 import torch
except ImportError:torch=None
from vision_features import build_features

@unittest.skipIf(torch is None,'Torch training environment required')
class RGBFeaturesTests(unittest.TestCase):
 def base(self):
  class Base(torch.nn.Module):
   def __init__(self):
    super().__init__();self.features=torch.nn.Identity();self.avgpool=torch.nn.AdaptiveAvgPool2d(1);self.classifier=torch.nn.Sequential(torch.nn.Identity(),torch.nn.Identity())
  return Base()
 def test_equal_luminance_colors_remain_distinct_in_rgb(self):
  red=torch.tensor([.587,0.,0.]).reshape(1,3,1,1);green=torch.tensor([0.,.299,0.]).reshape(1,3,1,1)
  rgb=build_features(self.base());gray=build_features(self.base(),grayscale=True)
  self.assertFalse(torch.allclose(rgb(red),rgb(green)))
  self.assertTrue(torch.allclose(gray(red),gray(green),atol=1e-6))
 def test_legacy_gray_weights_are_explicit_and_new_models_are_rgb(self):
  self.assertNotIn('gray',build_features(self.base()).state_dict())
  self.assertIn('gray',build_features(self.base(),grayscale=True).state_dict())
