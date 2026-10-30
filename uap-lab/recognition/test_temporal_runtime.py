import json,tempfile,unittest
from pathlib import Path
from temporal_model import fit
from temporal_runtime import TemporalRuntime
from native_tracks import NativeTracks
class TemporalRuntimeTests(unittest.TestCase):
 def test_turns_shape_and_restart_history_use_real_observations(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);path=root/'model.json';points=[dict(source_sha256='a',track_id='a',time=i/60,label='bird',bounds=dict(x=x,y=.2,w=.05,h=.05),shape_descriptor=[i/10]*64) for i,x in enumerate((.1,.11,.1))];path.write_text(json.dumps({'id':'model-one','temporal':fit(points)}))
   runtime=TemporalRuntime(path);runtime.refresh();tracker=NativeTracks('fixture')
   for i,p in enumerate(points):
    obs=tracker.update(i,p['time'],[[p['bounds']['x']*1000,200,50,50]])[0];obs['shape_descriptor']=p['shape_descriptor'];result=runtime.observe(obs,tracker.tracks[obs['proposed_track_id']],p['time'],1000,1000)
    if i==1:
     restored=NativeTracks('fixture');restored.tracks=json.loads(json.dumps(tracker.tracks));restored.serial=tracker.serial;restored.last_sequence=tracker.last_sequence;restored.last_pts=tracker.last_pts;tracker=restored
   self.assertEqual(result['nearest_label'],'bird');self.assertAlmostEqual(result['distance'],0);self.assertFalse(result['capture_control']);self.assertEqual(result['observations'],3)
 def test_no_model_or_no_confirmed_windows_never_invents_prediction(self):
  with tempfile.TemporaryDirectory() as tmp:
   runtime=TemporalRuntime(Path(tmp)/'missing.json');runtime.refresh();self.assertEqual(runtime.status()['state'],'unavailable')
   track={};obs={'box':[1,1,4,4],'shape_descriptor':[0]*64}
   for i in range(3):self.assertIsNone(runtime.observe(obs,track,i/60,100,100))
 def test_invalid_model_cannot_remain_active(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'model.json';path.write_text(json.dumps({'id':'bad','temporal':{'state':'trained','feature_names':[]}}));runtime=TemporalRuntime(path);runtime.refresh();self.assertIsNone(runtime.bank);self.assertIn('schema',runtime.error)
