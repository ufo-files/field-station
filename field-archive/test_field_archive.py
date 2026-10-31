import hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import field_archive as worker
class FieldArchiveTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.sid='20261029T230000Z-abcdef';self.sessions=self.root/'sessions';self.folder=self.sessions/self.sid;self.folder.mkdir(parents=True)
  self.entry={'name':'video.mkv','bytes':4,'sha256':hashlib.sha256(b'data').hexdigest()};self.job={'id':self.sid,'files':[self.entry]}
  worker.save(self.folder/'archive-decision.json',dict(schema=2,source='station_web_ui',session_id=self.sid,human_confirmed=True,confirmed_anomalous=True,bundle_ready=True,videos=['video.mp4','video-annotated.mp4'],reviewed_epoch=1))
  self.patches=[patch.object(worker,'DATA',self.root/'transfer'),patch.object(worker,'SESSIONS',self.sessions),patch.object(worker,'PRIVATE',self.root/'private')];[p.start() for p in self.patches]
 def tearDown(self):
  [p.stop() for p in reversed(self.patches)];self.tmp.cleanup()
 def test_provisional_never_contacts_m6(self):
  (self.folder/'archive-decision.json').unlink()
  worker.save(self.folder/'manifest.json',{'id':self.sid,'capture_origin':'provisional_motion'})
  with patch.object(worker,'remote') as remote:self.assertFalse(worker.transfer(self.job));remote.assert_not_called()
 def test_private_credentials_cannot_be_transferred(self):
  with self.assertRaisesRegex(ValueError,'Private configuration'):worker.source(self.job,dict(self.entry,private_source='credentials.json'))
 def test_wrong_remote_receipt_never_marks_verified(self):
  worker.save(self.folder/'manifest.json',{'id':self.sid,'capture_origin':'manual'})
  with patch.object(worker,'remote',return_value={'state':'verified','receipt':{'fingerprint':'wrong','files':[]}}):
   with self.assertRaisesRegex(ValueError,'receipt'):worker.transfer(self.job)
  self.assertFalse((worker.DATA/'receipts'/(self.sid+'.json')).exists())
 def test_matching_remote_receipt_is_saved_without_reupload(self):
  worker.save(self.folder/'manifest.json',{'id':self.sid,'capture_origin':'manual'});index=worker.inventory(self.job);receipt={'fingerprint':worker.validate(index),'files':index['files']}
  with patch.object(worker,'remote',return_value={'state':'verified','receipt':receipt}) as remote:
   self.assertTrue(worker.transfer(self.job));self.assertFalse(worker.transfer(self.job));self.assertEqual(remote.call_count,1)
