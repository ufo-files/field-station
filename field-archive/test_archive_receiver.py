import hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from archive_receiver import prepare,verify,validate,paths
class ReceiverTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=b'original evidence';self.index={'schema':1,'session_id':'20261029T230000Z-abcdef','files':[{'name':'video.mkv','bytes':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest()}]}
 def tearDown(self):self.tmp.cleanup()
 def test_verified_receipt_is_idempotent_and_preserves_bytes(self):
  r=prepare(self.root,self.index,0);incoming,final,fp=paths(self.root,self.index);(incoming/'video.mkv').write_bytes(self.data)
  receipt=verify(self.root,self.index);self.assertEqual((final/'video.mkv').read_bytes(),self.data);self.assertEqual(receipt['fingerprint'],fp);self.assertEqual(verify(self.root,self.index),receipt);self.assertEqual(prepare(self.root,self.index,0)['state'],'verified')
 def test_changed_evidence_is_not_finalized(self):
  prepare(self.root,self.index,0);incoming,final,_=paths(self.root,self.index);(incoming/'video.mkv').write_bytes(b'x'*len(self.data))
  with self.assertRaisesRegex(ValueError,'SHA256'):verify(self.root,self.index)
  self.assertFalse(final.exists());self.assertTrue(incoming.exists())
 def test_reserve_and_unsafe_paths_fail_closed(self):
  with self.assertRaisesRegex(ValueError,'reserve'):prepare(self.root,self.index,10**18)
  self.index['files'][0]['name']='../escape'
  with self.assertRaisesRegex(ValueError,'Unsafe'):validate(self.index)
 def test_symlink_is_not_evidence(self):
  prepare(self.root,self.index,0);incoming,final,_=paths(self.root,self.index);source=self.root/'external';source.write_bytes(self.data);(incoming/'video.mkv').symlink_to(source)
  with self.assertRaisesRegex(ValueError,'Unsafe'):verify(self.root,self.index)
