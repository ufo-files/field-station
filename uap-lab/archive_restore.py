"""Restore original session video from a verified private offload package."""
import fcntl,hashlib,json,re,tarfile,tempfile
from pathlib import Path
from label_queue import read

def _restore_private(folder):
 folder=Path(folder);root=folder.parent.parent;sid=folder.name
 if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Invalid session')
 record=read(root/'retention/receipts'/(sid+'.json'),{})
 key=record.get('receipt',{}).get('verified_archive','')
 if not re.fullmatch('[a-f0-9]{64}',key):return False
 for base in read(root/'retention-policy.json',{}).get('review_archive_roots',[]):
  archive=Path(base);package=archive/key
  if not package.is_dir() or package.is_symlink():continue
  with (archive/'receiver.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_SH)
   unit=read(package/'manifest.json',{});receipt=read(package/'receipt.json',{})
   fingerprint=hashlib.sha256(json.dumps(unit,sort_keys=True,separators=(',',':')).encode()).hexdigest()
   if fingerprint!=key or unit.get('session')!=sid or receipt.get('session')!=sid or receipt.get('fingerprint')!=key or not receipt.get('verified'):continue
   source=package/'recording.tar'
   if not source.is_file() or source.is_symlink():continue
   name='sessions/'+sid+'/video.mkv';entry=next((f for f in unit.get('files',[]) if f['path']==name),None)
   if not entry:continue
   with tarfile.open(source,'r:') as bundle:
    member=bundle.getmember(name)
    if not member.isfile() or member.size!=entry['bytes']:raise ValueError('Archived original size mismatch')
    with bundle.extractfile(member) as inp,tempfile.NamedTemporaryFile(dir=folder,prefix='.archive-restore-',delete=False) as out:
     target=Path(out.name);digest=hashlib.sha256()
     try:
      for chunk in iter(lambda:inp.read(4*1024**2),b''):digest.update(chunk);out.write(chunk)
      out.flush()
      if digest.hexdigest()!=entry['sha256']:raise ValueError('Archived original checksum mismatch')
      out.close();target.replace(folder/'video.mkv')
     finally:target.unlink(missing_ok=True)
   return True
 return False


def restore_original(folder):
 if _restore_private(folder):return True
 # A previously verified public bundle retains the full native original even
 # after the fast SSD copy has been reclaimed.
 import urllib.request
 folder=Path(folder);receipt=read(folder/'manifest.json',{}).get('internet_archive',{})
 identifier=receipt.get('identifier','');entry=next((e for e in receipt.get('files',[]) if e.get('name')=='video.mkv'),None)
 if not receipt.get('verified_at') or not entry or not re.fullmatch('[A-Za-z0-9_.-]+',identifier):return False
 with tempfile.NamedTemporaryFile(dir=folder,prefix='.archive-original-',delete=False) as out:
  target=Path(out.name);digest=hashlib.sha256();size=0
  try:
   with urllib.request.urlopen('https://archive.org/download/'+identifier+'/video.mkv',timeout=90) as response:
    for chunk in iter(lambda:response.read(4*1024**2),b''):size+=len(chunk);digest.update(chunk);out.write(chunk)
   out.flush()
   if size!=entry['bytes'] or digest.hexdigest()!=entry['sha256']:raise ValueError('Restored Archive original checksum mismatch')
   out.close();target.replace(folder/'video.mkv')
  finally:target.unlink(missing_ok=True)
 return True
