"""Release an automatic overflow cache only after verified main-Mini handoff."""
import hashlib,json,os,re,time
from pathlib import Path

def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(4*1024**2),b''):h.update(b)
 return h.hexdigest()
def release_cached_archive(root,sessions,key,proof,remote_unit,url):
 root=Path(root);sessions=Path(sessions)
 if not re.fullmatch('[a-f0-9]{64}',key):raise ValueError('Invalid archive identity')
 folder=root/key
 if folder.is_symlink() or folder.resolve().parent!=root.resolve():raise ValueError('Unsafe archive path')
 unit=json.loads((folder/'manifest.json').read_text());receipt=json.loads((folder/'receipt.json').read_text())
 if fingerprint(unit)!=key or fingerprint(remote_unit)!=key or not receipt.get('verified') or receipt.get('fingerprint')!=key or not proof.get('verified_at'):raise ValueError('Main archive not verified')
 sid=unit['session']
 if not re.fullmatch('[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Unsupported source identity')
 source_manifest=json.loads((sessions/sid/'manifest.json').read_text())
 if source_manifest.get('capture_origin')!='provisional_motion' or 'manual' in str(source_manifest.get('title','')).lower():raise ValueError('Manual or unknown recording protected')
 target=folder/'recording.tar';marker=folder/'remote-copy.json'
 if not target.exists():
  if marker.exists() and json.loads(marker.read_text()).get('verified'):return dict(already_offloaded=True,bytes=0)
  raise ValueError('Local archive missing without handoff receipt')
 if target.is_symlink() or digest(target)!=proof.get('hashes',{}).get('recording.tar'):raise ValueError('Overflow archive changed after verification')
 size=target.stat().st_size
 record=dict(verified=True,fingerprint=key,session=sid,bytes=size,sha256=proof['hashes']['recording.tar'],url=url,epoch=time.time(),manual_recording=False)
 temp=marker.with_suffix('.tmp')
 with temp.open('w') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
 temp.replace(marker)
 fd=os.open(folder,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
 target.unlink()
 return dict(offloaded=True,bytes=size)
