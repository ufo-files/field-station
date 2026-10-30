import json,random,sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).parent.parent))
from native_tracks import NativeTracks
from native_tracks_reference import NativeTracks as Reference
from temporal_features_fast import feature_window
from temporal_model import feature_window as reference_features
from classification_policy import eligible,apply_results

class LatencyTests(unittest.TestCase):
 def test_dense_tracks_preserve_identity_and_ambiguity(self):
  rng=random.Random(731);a=NativeTracks('test');b=Reference('test')
  for frame in range(100):
   boxes=[[rng.randrange(0,1920),rng.randrange(0,1080),rng.randrange(3,30),rng.randrange(3,30)] for _ in range(140)]
   x=a.update(frame,frame/60,boxes);y=b.update(frame,frame/60,boxes)
   self.assertEqual(x,y)
   if frame==40:
    a.tracks=json.loads(json.dumps(a.tracks));b.tracks=json.loads(json.dumps(b.tracks))
 def test_temporal_features_match_training_schema(self):
  rng=random.Random(42)
  for _ in range(500):
   pts=[dict(time=5+i*.0167,bounds=dict(x=rng.random(),y=rng.random(),w=.01+rng.random(),h=.01+rng.random()),shape_descriptor=[rng.random() for _ in range(64)]) for i in range(3)]
   np.testing.assert_allclose(feature_window(pts),reference_features(pts),rtol=1e-12,atol=1e-12)
 def test_small_observations_retained_without_fabricated_scores(self):
  policy=dict(version='v',minimum_native_size=8,thresholds={'bird':.9})
  obs=[dict(box=[0,0,4,4],proposed_track_id='small'),dict(box=[0,0,8,3],proposed_track_id='large')]
  indices=[i for i,o in enumerate(obs) if eligible(o,policy)]
  self.assertEqual(indices,[1]);apply_results(obs,indices,[{'scores':{'bird':.95}}],policy)
  self.assertEqual(len(obs),2);self.assertEqual(obs[0]['suggested_label'],'unknown');self.assertEqual(obs[0]['scores'],{})
  self.assertEqual(obs[1]['suggested_label'],'bird')
 def test_eligible_observation_cannot_be_silently_omitted(self):
  with self.assertRaises(ValueError):apply_results([dict(box=[0,0,8,8])],[],[],dict(minimum_native_size=8,version='v'))
if __name__=='__main__':unittest.main()
