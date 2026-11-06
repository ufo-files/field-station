"""Restore original session video from a verified private offload package."""
import fcntl,hashlib,json,re,tarfile,tempfile
from pathlib import Path
from label_queue import read

def restore_original(folder):
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
