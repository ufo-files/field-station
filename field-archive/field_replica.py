"""Offline-first, non-destructive field-to-main replication. No IA dependency."""
import argparse,base64,fcntl,hashlib,json,os,plistlib,re,shlex,subprocess,time
from pathlib import Path


def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp')
 with t.open('w') as f:json.dump(v,f);f.flush();os.fsync(f.fileno())
 t.replace(p)

def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024**2),b''):h.update(b)
 return h.hexdigest()

def error_summary(exc):
 if isinstance(exc,subprocess.CalledProcessError):return 'Transfer command failed (exit '+str(exc.returncode)+'); retry pending'
 if isinstance(exc,subprocess.TimeoutExpired):return 'Transfer timed out; retry pending'
 return str(exc)[:500]

def safe(name):
 p=Path(name)
 if p.is_absolute() or '..' in p.parts or not p.parts:raise ValueError('Unsafe relative path')
 return p

INVENTORY='''
import json,re
from pathlib import Path
r=Path('/Volumes/UFO-Field'); units=[];seen=set()
def read(p,d):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return d
ids=[x.get('session_id','') for x in read(r/'uap-lab/live/manual-sessions.json',[])]
jobs=Path('/Users/ufo-field/ufo-field/capture-station/private/internet-archive/jobs')
ids += [p.stem for p in jobs.glob('*.json') if read(p,{}).get('state') not in ('withdrawn','cancelled')]
for sid in ids:
 if sid in seen or not re.fullmatch('[0-9TZ]+-[a-f0-9]{6}',sid):continue
 seen.add(sid);p=r/'sessions'/sid;m=read(p/'manifest.json',{})
 if m.get('state') not in ('completed','interrupted') or not (p/'video.mp4').is_file():continue
 units.append(('sessions/'+sid,p))
for p in sorted((r/'auto-training/candidates').iterdir()):
 if re.fullmatch('[a-f0-9]{64}',p.name) and p.name in PUBLISHED:units.append(('models/'+p.name,p))
result=[]
for name,folder in units:
 files={}
 for p in sorted(folder.rglob('*')):
  if p.is_symlink() or not p.is_file() or any(x.is_symlink() for x in p.parents if x!=folder and x.is_relative_to(folder)):continue
  if p.name.endswith(('.tmp','.lock')):continue
  s=p.stat();files[str(p.relative_to(folder))]=[s.st_size,s.st_mtime_ns]
 if files:result.append(dict(name=name,source=str(folder),files=files))
archive=Path('/Volumes/UFO-SWR/field-archive')
for folder in sorted(archive.iterdir()) if archive.is_dir() else []:
 if not re.fullmatch('[a-f0-9]{64}',folder.name) or folder.is_symlink():continue
 receipt=read(folder/'receipt.json',{})
 if not receipt.get('verified') or not (folder/'recording.tar').is_file():continue
 files={}
 for name in ['manifest.json','receipt.json','recording.tar']:
  p=folder/name
  if p.is_symlink():raise ValueError('Unsafe overflow file')
  st=p.stat();files[name]=[st.st_size,st.st_mtime_ns]
 result.append(dict(name='overflow/'+folder.name,source=str(folder),files=files))
print(json.dumps(result))
'''

def run(cfg):
 volume=Path(cfg['volume']);info=plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist',str(volume)]))
 if not volume.is_mount() or info.get('VolumeUUID')!=cfg['uuid']:raise ValueError('Archive drive unavailable')
 root=volume/'field-replica';root.mkdir(exist_ok=True)
 with (root/'worker.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  state=dict(started=time.time(),phase='connecting',verified=[],errors=[]);save(root/'status.json',state)
  def remote(code):
   payload=base64.b64encode(code.encode()).decode()
   return subprocess.check_output([cfg['python'],cfg['ssh_helper'],'python3 -c '+shlex.quote("import base64;exec(base64.b64decode("+repr(payload)+"))")],timeout=600,text=True)
  published=[]
  for p in Path(cfg['publication_receipts']).glob('*.json'):
   j=json.loads(p.read_text())
   if j.get('state')=='published' and j.get('assets',{}).get('model.tar.gz'):published.append(p.stem)
  try:units=json.loads(remote('PUBLISHED='+repr(published)+'\n'+INVENTORY))
  except Exception as exc:
   state.update(phase='offline_retry_pending',error=error_summary(exc));save(root/'status.json',state);return
  creds={}
  for line in Path(cfg['credentials']).read_text().splitlines():
   k,sep,v=line.partition(':')
   if sep:creds[k.strip().lower()]=v.strip()
  env=os.environ.copy();env.update(SSH_ASKPASS=cfg['askpass'],SSH_ASKPASS_REQUIRE='force',DISPLAY='field-replica')
  state['total']=len(units)
  for unit in units:
   if not volume.is_mount():raise ValueError('Archive drive disconnected')
   name=unit['name'];dest=root/safe(name);dest.mkdir(parents=True,exist_ok=True)
   receipt=dest/'.replica-receipt.json'
   old=json.loads(receipt.read_text()) if receipt.exists() else {}
   changed=[n for n,s in unit['files'].items() if old.get('source_signatures',{}).get(n)!=s or not (dest/safe(n)).is_file() or (dest/n).stat().st_size!=s[0] or old.get('destination_signatures',{}).get(n)!=[(dest/n).stat().st_size,(dest/n).stat().st_mtime_ns]]
   def handoff():
    if not name.startswith('overflow/') or not cfg.get('archive_bridge'):return
    proof=json.loads(receipt.read_text())
    if not proof.get('verified_at'):return
    key=name.split('/')[1]
    code='''import sys,json
from pathlib import Path
from urllib.request import Request,urlopen
sys.path.insert(0,'/Users/ufo-field/ufo-field/field-archive')
from archive_handoff import release_cached_archive
cfg=json.loads((Path.home()/'.config/ufo-files/archive-bridge.json').read_text())
url=cfg['url']+'/v1/'+KEY+'/manifest.json'
with urlopen(Request(url,headers={'Authorization':'Bearer '+cfg['token']}),timeout=30) as response:unit=json.load(response)
print(json.dumps(release_cached_archive('/Volumes/UFO-SWR/field-archive','/Volumes/UFO-Field/sessions',KEY,PROOF,unit,cfg['url']+'/v1/'+KEY)))'''.replace('KEY',repr(key)).replace('PROOF',repr(proof))
    result=json.loads(remote(code));state['offloaded_bytes']=state.get('offloaded_bytes',0)+result.get('bytes',0)
   if not changed:
    state['verified'].append(name)
    try:handoff()
    except Exception as exc:state['errors'].append(dict(unit=name,error=error_summary(exc)))
    continue
   state.update(phase='transferring',current=name,changed_files=len(changed));save(root/'status.json',state)
   try:
    args=[cfg['rsync'],'-rt','--partial','--partial-dir=.transfer-partial','--timeout=60','--exclude=*.tmp','--exclude=*.lock','--exclude=*.sock','-e','ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new',creds['username']+'@'+creds['ip']+':'+unit['source']+'/',str(dest)+'/']
    subprocess.run(args,env=env,stdin=subprocess.DEVNULL,start_new_session=True,check=True,timeout=3600,stdout=subprocess.DEVNULL)
    code='''import hashlib,json
from pathlib import Path
root=Path(SOURCE);out={}
for n in NAMES:
 p=root/n
 if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe source')
 before=p.stat();h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024**2),b''):h.update(b)
 after=p.stat()
 if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed')
 out[n]=dict(sha256=h.hexdigest(),signature=[after.st_size,after.st_mtime_ns])
print(json.dumps(out))'''.replace('SOURCE',repr(unit['source'])).replace('NAMES',repr(changed))
    hashes=json.loads(remote(code));proof=dict(old.get('hashes',{}));signatures=dict(old.get('source_signatures',{}));destination=dict(old.get('destination_signatures',{}));pending=[]
    for n,e in hashes.items():
     p=dest/safe(n)
     if p.is_symlink() or not p.resolve().is_relative_to(dest.resolve()) or e['signature']!=unit['files'][n] or digest(p)!=e['sha256']:
      pending.append(n);continue
     proof[n]=e['sha256'];signatures[n]=unit['files'][n];destination[n]=[p.stat().st_size,p.stat().st_mtime_ns]
    if proof:save(receipt,dict(verified_at=None if pending else time.time(),source=unit['source'],source_signatures=signatures,destination_signatures=destination,hashes=proof,pending_files=pending,source_deleted=False))
    if pending:raise ValueError('Changed or corrupt files will retry: '+', '.join(pending[:5]))
    state['verified'].append(name);handoff()
   except Exception as exc:state['errors'].append(dict(unit=name,error=error_summary(exc)))
   save(root/'status.json',state)
  state.update(phase='retry_pending' if state['errors'] else 'complete',current=None,finished=time.time());save(root/'status.json',state)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();run(json.loads(Path(a.config).read_text()))
