import hashlib,json,plistlib,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import field_replica as r

class ReplicaTests(unittest.TestCase):
 def test_paths_reject_escape(self):
  for name in ('/etc/passwd','../outside','a/../../outside',''):
   with self.assertRaises(ValueError):r.safe(name)
 def exercise(self,corrupt=False):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';source.mkdir();video=source/'video.mp4';video.write_bytes(b'manual-original');s=video.stat()
   creds=root/'creds';creds.write_text('username: test\nip: example\n');receipts=root/'published';receipts.mkdir()
   unit=dict(name='sessions/20261109T055133Z-704e15',source=str(source),files={'video.mp4':[s.st_size,s.st_mtime_ns]})
   cfg=dict(volume=str(root),uuid='test',python='python',ssh_helper='ssh-helper',credentials=str(creds),askpass='askpass',rsync='rsync',publication_receipts=str(receipts))
   calls=[]
   def output(args,**kw):
    if args[0]=='/usr/sbin/diskutil':return plistlib.dumps(dict(VolumeUUID='test'))
    import base64,re
    payload=re.search("b64decode\\('([^']+)'\\)",__import__('shlex').split(args[-1])[-1]).group(1)
    code=base64.b64decode(payload).decode()
    if 'PUBLISHED=' in code:return json.dumps([unit])
    return json.dumps({'video.mp4':dict(sha256=hashlib.sha256(video.read_bytes()).hexdigest(),signature=unit['files']['video.mp4'])})
   def transfer(args,**kw):
    calls.append(args);dest=Path(args[-1]);shutil.copy2(video,dest/'video.mp4')
    if corrupt:(dest/'video.mp4').write_bytes(b'broken')
   with patch.object(Path,'is_mount',return_value=True),patch.object(r.subprocess,'check_output',side_effect=output),patch.object(r.subprocess,'run',side_effect=transfer):
    r.run(cfg)
    receipt=root/'field-replica'/unit['name']/'.replica-receipt.json'
    if corrupt:
     self.assertFalse(receipt.exists());self.assertEqual(json.loads((root/'field-replica/status.json').read_text())['phase'],'retry_pending')
    else:
     self.assertTrue(receipt.exists());r.run(cfg);self.assertEqual(len(calls),1)
     self.assertNotIn('--delete',calls[0]);self.assertFalse(json.loads(receipt.read_text())['source_deleted'])
    self.assertEqual(video.read_bytes(),b'manual-original')
 def test_verified_copy_is_incremental_and_preserves_source(self):self.exercise()
 def test_corruption_is_not_confirmed(self):self.exercise(True)
 def test_offline_is_retryable(self):
  with tempfile.TemporaryDirectory() as d:
   cfg=dict(volume=d,uuid='test',python='python',ssh_helper='ssh',publication_receipts=d)
   with patch.object(Path,'is_mount',return_value=True),patch.object(r.subprocess,'check_output',side_effect=[plistlib.dumps(dict(VolumeUUID='test')),OSError('offline')]):r.run(cfg)
   self.assertEqual(json.loads((Path(d)/'field-replica/status.json').read_text())['phase'],'offline_retry_pending')
if __name__=='__main__':unittest.main()
