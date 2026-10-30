import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import deploy
class MarkerTests(unittest.TestCase):
 def test_verified_release_publishes_cleanup_marker_idempotently(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'candidate';folder.mkdir();cfg=root/'config.json'
   def save(p,d):p.write_text(json.dumps(d))
   save(cfg,{'spool':str(root/'capture-spool')});save(folder/'candidate-policy.json',{'version':'new'});save(folder/'promotion-evaluation.json',{'passed':True,'baseline_version':'old'});save(folder/'activation.json',{'phase':'monitoring'})
   meta=dict(version='new',previous_version='old',deployed_epoch=100)
   with patch.object(deploy,'CONFIG',cfg),patch.object(deploy,'status',return_value=dict(version='new',health=dict(model='new',updated_epoch=time.time()))) as status:
    deploy.release(folder,meta);deploy.release(folder,meta);status.assert_called_once()
   marker=root/'notifications/active-model-release.json';self.assertEqual(json.loads(marker.read_text())['version'],'new')
   save(marker,dict(version='later',deployed_epoch=200))
   with patch.object(deploy,'CONFIG',cfg):deploy.release(folder,meta)
   self.assertEqual(json.loads(marker.read_text())['version'],'later')
 def test_failed_release_never_sets_cleanup_marker(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for name,data in [('candidate-policy',{'version':'new'}),('promotion-evaluation',{'passed':False,'baseline_version':'old'}),('activation',{'phase':'rolled_back'})]:(root/(name+'.json')).write_text(json.dumps(data))
   with self.assertRaises(ValueError):deploy.release(root,dict(version='new',previous_version='old'))
   self.assertFalse((root/'notifications').exists())
