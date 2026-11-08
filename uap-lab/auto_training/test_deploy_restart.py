import unittest
from unittest.mock import patch
from types import SimpleNamespace
import deploy
class RestartTests(unittest.TestCase):
 def test_exited_registered_job_is_started(self):
  with patch.object(deploy.subprocess,'run',side_effect=[SimpleNamespace(returncode=0),SimpleNamespace(returncode=1),SimpleNamespace(returncode=0)]) as run:
   deploy.restart_recognition()
  self.assertEqual(run.call_args_list[-1].args[0][1],'kickstart')
 def test_running_job_gets_only_graceful_signal(self):
  with patch.object(deploy.subprocess,'run',side_effect=[SimpleNamespace(returncode=0),SimpleNamespace(returncode=0)]) as run:
   deploy.restart_recognition()
  self.assertEqual(run.call_count,2)
if __name__=='__main__':unittest.main()
