import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from mail_alerts import save,read
from model_releases import deliver
class ReleaseTests(unittest.TestCase):
 def test_success_is_sent_once(self):
  with tempfile.TemporaryDirectory() as t:
   folder=Path(t);save(folder/'release.json',dict(state='deployed',health_verified=True,version='a'*64,previous_version='b'*64,deployed_epoch=1,labels={'cloud':34}))
   send=Mock();cfg=dict(sender='contact@ufo-files.app',recipient='glenn.sorrentino@pm.me')
   self.assertEqual(deliver(folder,cfg,send,Mock())['state'],'accepted_by_mail');deliver(folder,cfg,send,Mock());send.assert_called_once();self.assertIn('cloud: 34',send.call_args.args[1])
 def test_uncertain_submission_is_not_duplicated(self):
  with tempfile.TemporaryDirectory() as t:
   folder=Path(t);save(folder/'release.json',dict(state='deployed',health_verified=True,version='a'*64,previous_version='b'*64,deployed_epoch=1))
   send=Mock(side_effect=TimeoutError());cfg=dict(sender='sender',recipient='recipient')
   self.assertEqual(deliver(folder,cfg,send,Mock())['state'],'uncertain');deliver(folder,cfg,send,Mock());send.assert_called_once()
 def test_rejected_candidate_cannot_send(self):
  with tempfile.TemporaryDirectory() as t:
   folder=Path(t);save(folder/'release.json',dict(state='rejected',health_verified=False));send=Mock()
   with self.assertRaises(ValueError):deliver(folder,{},send,Mock())
   send.assert_not_called()
