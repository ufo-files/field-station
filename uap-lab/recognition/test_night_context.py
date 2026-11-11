import unittest
from unittest.mock import Mock,patch
from night_context import predict,enabled
from crop_geometry import context_bounds
from classification_policy import apply_results
class NightContextTests(unittest.TestCase):
 def policy(self):return dict(version='v',input_color_space='RGB',classes=['anomalous','not_anomalous'],minimum_native_size=3,thresholds={'anomalous':.85},night_context_confirmation=dict(enabled=True,version='v',minimum_context_score=.001))
 def test_context_rejects_only_strong_negative_and_retains_scores(self):
  worker=Mock();worker.predict.side_effect=[[{'scores':{'anomalous':.99,'not_anomalous':.01}},{'scores':{'anomalous':.9,'not_anomalous':.1}},{'scores':{'anomalous':.1,'not_anomalous':.9}}],[{'scores':{'anomalous':.0001,'not_anomalous':.9999}},{'scores':{'anomalous':.1,'not_anomalous':.9}}]]
  result=predict(worker,[b'a',b'b',b'c'],[b'A',b'B',b'C'],self.policy(),'frame')
  self.assertEqual(worker.predict.call_args.args[0],[b'A',b'B'])
  observations=[{'box':[0,0,4,4]} for _ in result];apply_results(observations,[0,1,2],result,self.policy())
  self.assertEqual([o['suggested_label'] for o in observations],['not_anomalous','anomalous','not_anomalous'])
  self.assertEqual(observations[0]['scores']['anomalous'],.99)
 def test_no_extra_work_in_daytime(self):
  worker=Mock();worker.predict.return_value=[];self.assertEqual(predict(worker,[],[],self.policy(),'day'),[]);worker.predict.assert_called_once()
 def test_missing_context_is_error_not_negative(self):
  worker=Mock();worker.predict.side_effect=[[{'scores':{'anomalous':.9}}],[{'error':'worker failed'}]]
  with self.assertRaises(ValueError):predict(worker,[b'a'],[b'A'],self.policy(),'bad')
 def test_only_qualified_rgb_model_at_night(self):
  with patch('night_context.boundaries',return_value=(100,200)):
   self.assertTrue(enabled(self.policy(),250));self.assertFalse(enabled(self.policy(),150))
   self.assertFalse(enabled(dict(self.policy(),version='other'),250));self.assertFalse(enabled(dict(self.policy(),input_color_space='grayscale'),250))
   self.assertFalse(enabled(self.policy(),float('nan')))
 def test_geometry_matches_review_and_stays_in_frame(self):
  self.assertEqual(context_bounds([100,100,4,4],1920,1080),[70,70,64,64])
  self.assertEqual(context_bounds([0,0,4,4],1920,1080),[0,0,64,64])
  self.assertEqual(context_bounds([1916,1076,4,4],1920,1080),[1856,1016,64,64])
  self.assertEqual(context_bounds([100,100,100,80],1920,1080),[88,88,124,104])
  with self.assertRaises(ValueError):context_bounds([-1,0,4,4],1920,1080)
