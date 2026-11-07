import unittest
from pathlib import Path
from unittest.mock import patch
import deploy
class ActivationRetryTests(unittest.TestCase):
 def test_retry_does_not_replace_previous_model_backup(self):
  folder=Path('/model');cfg={'policy':'/policy'}
  records={str(deploy.CONFIG):cfg,'/policy':{'version':'new'},str(folder/'candidate-policy.json'):{'version':'new'},str(folder/'promotion-evaluation.json'):{'passed':True},str(folder/'station-probe.json'):{'ready':True,'candidate_version':'new'}}
  with patch.object(deploy,'read',side_effect=lambda p:records[str(p)] if str(p) in records else (_ for _ in ()).throw(FileNotFoundError(str(p)))),patch.object(deploy,'deployment_approved',return_value=True),patch.object(deploy,'status',return_value={'health':{'model':'old','error':'decoder stopped'}}),patch.object(deploy,'restart_recognition') as restart,patch.object(deploy,'save') as save:
   self.assertEqual(deploy.activate(folder)['version'],'new');restart.assert_called_once()
   self.assertTrue(all(call.args[0].name=='activation.json' for call in save.call_args_list))

 def test_monitoring_retry_does_not_restart_a_slow_runtime(self):
  folder=Path('/model');records={str(deploy.CONFIG):{'policy':'/policy'},'/policy':{'version':'new'},str(folder/'candidate-policy.json'):{'version':'new'},str(folder/'promotion-evaluation.json'):{'passed':True},str(folder/'station-probe.json'):{'ready':True,'candidate_version':'new'},str(folder/'activation.json'):{'phase':'monitoring','version':'new'}}
  with patch.object(deploy,'read',side_effect=lambda p:records[str(p)]),patch.object(deploy,'deployment_approved',return_value=True),patch.object(deploy,'restart_recognition') as restart,patch.object(deploy,'save'):
   deploy.activate(folder);restart.assert_not_called()
