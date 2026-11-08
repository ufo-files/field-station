import hashlib,io,json,tarfile,tempfile,unittest
from pathlib import Path
from archive_restore import restore_original
class RestoreTests(unittest.TestCase):
 def test_verified_package_restores_original_and_rejects_tampering(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);sid='20261104T061554Z-f69d48';folder=root/'sessions'/sid;folder.mkdir(parents=True);archive=root/'archive';archive.mkdir()
   payload=b'original camera packets';name='sessions/'+sid+'/video.mkv'
   unit=dict(session=sid,files=[dict(path=name,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())]);key=hashlib.sha256(json.dumps(unit,sort_keys=True,separators=(',',':')).encode()).hexdigest();package=archive/key;package.mkdir()
   def save(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))
   save(root/'retention-policy.json',dict(review_archive_roots=[str(archive)]));save(root/'retention/receipts'/(sid+'.json'),dict(receipt=dict(verified_archive=key)))
   save(package/'manifest.json',unit);save(package/'receipt.json',dict(verified=True,session=sid,fingerprint=key))
   def bundle(data):
    with tarfile.open(package/'recording.tar','w') as out:
     member=tarfile.TarInfo(name);member.size=len(data);out.addfile(member,io.BytesIO(data))
   bundle(payload);self.assertTrue(restore_original(folder));self.assertEqual((folder/'video.mkv').read_bytes(),payload)
   (folder/'video.mkv').unlink();bundle(b'x'*len(payload))
   with self.assertRaisesRegex(ValueError,'checksum'):restore_original(folder)
   self.assertFalse((folder/'video.mkv').exists());self.assertFalse(list(folder.glob('.archive-restore-*')))
   save(package/'receipt.json',dict(verified=False,session=sid,fingerprint=key));self.assertFalse(restore_original(folder))

 def test_public_original_restores_only_after_matching_verified_checksum(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/'sessions/20261106T021933Z-b3ccb7';folder.mkdir(parents=True);payload=b'full original'
   receipt=dict(verified_at=1,identifier='test-item',files=[dict(name='video.mkv',bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())])
   (folder/'manifest.json').write_text(json.dumps(dict(internet_archive=receipt)))
   with patch('urllib.request.urlopen',return_value=io.BytesIO(payload)):
    self.assertTrue(restore_original(folder))
   self.assertEqual((folder/'video.mkv').read_bytes(),payload);(folder/'video.mkv').unlink()
   with patch('urllib.request.urlopen',return_value=io.BytesIO(b'wrong')),self.assertRaisesRegex(ValueError,'checksum'):restore_original(folder)
   self.assertFalse((folder/'video.mkv').exists())
