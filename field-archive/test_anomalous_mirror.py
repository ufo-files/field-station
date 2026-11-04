import hashlib,io,tempfile,unittest
from pathlib import Path
from anomalous_mirror import mirror
class MirrorTests(unittest.TestCase):
 def job(self):return {'identifier':'test-bundle','files':[{'name':'frames/original.png','bytes':3,'sha256':hashlib.sha256(b'abc').hexdigest()}]}
 def test_verified_bundle_is_reused(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=mirror(self.job(),Path(tmp),lambda *a,**kw:io.BytesIO(b'abc'))
   self.assertTrue(r['verified'])
   mirror(self.job(),Path(tmp),lambda *a,**kw:self.fail('Unexpected download'))
 def test_corrupt_download_never_gets_receipt(self):
  with tempfile.TemporaryDirectory() as tmp:
   with self.assertRaises(ValueError):mirror(self.job(),Path(tmp),lambda *a,**kw:io.BytesIO(b'bad'))
   self.assertFalse(list(Path(tmp).rglob('.archive-copy.json')))
 def test_unsafe_filename_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   j=self.job();j['files'][0]['name']='../outside'
   with self.assertRaises(ValueError):mirror(j,Path(tmp))
