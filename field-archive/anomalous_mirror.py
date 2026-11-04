"""Keep checksum-verified copies of IA evidence on a separate archive volume."""
import argparse,fcntl,hashlib,json,os,re,shlex,subprocess,time,urllib.request
from pathlib import Path, PurePosixPath


def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix('.tmp')
 with tmp.open('w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
 tmp.replace(path)


def entries(job):
 result=[]
 for e in job['files']:
  p=PurePosixPath(e['name'])
  if p.is_absolute() or '..' in p.parts or not p.parts or not re.fullmatch('[a-f0-9]{64}',e['sha256']):raise ValueError('Unsafe archive entry')
  result.append({k:e[k] for k in ('name','bytes','sha256')})
 return result


def matches(path,entry):
 if path.is_symlink() or not path.is_file() or path.stat().st_size!=entry['bytes']:return False
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(4*1024**2),b''):h.update(b)
 return h.hexdigest()==entry['sha256']


def mirror(job,dest,fetch=urllib.request.urlopen):
 from urllib.parse import quote
 identifier=job['identifier']
 if not re.fullmatch('[A-Za-z0-9_.-]+',identifier) or identifier in ('.','..'):raise ValueError('Unsafe identifier')
 files=entries(job);revision=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
 folder=dest/identifier/revision;folder.mkdir(parents=True,exist_ok=True)
 for e in files:
  p=folder/e['name'];p.parent.mkdir(parents=True,exist_ok=True)
  if not p.resolve().is_relative_to(folder.resolve()) or p.is_symlink():raise ValueError('Unsafe destination')
  if matches(p,e):continue
  tmp=p.with_name(p.name+'.download')
  h=hashlib.sha256();size=0
  with fetch('https://archive.org/download/'+quote(identifier)+'/'+quote(e['name'],safe='/'),timeout=90) as response,tmp.open('wb') as f:
   while True:
    b=response.read(4*1024**2)
    if not b:break
    size+=len(b);h.update(b);f.write(b)
   f.flush();os.fsync(f.fileno())
  if size!=e['bytes'] or h.hexdigest()!=e['sha256']:
   tmp.unlink();raise ValueError('Archive download checksum mismatch: '+e['name'])
  tmp.replace(p)
 receipt=dict(verified=True,identifier=identifier,files=files,path=str(folder),verified_at=time.time())
 save(folder/'.archive-copy.json',receipt)
 return receipt


def run(cfg):
 volume=Path(cfg['volume'])
 import plistlib
 info=plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(volume)]))
 if not volume.is_mount() or info.get('VolumeUUID')!=cfg['uuid']:raise ValueError('Archive volume unavailable')
 dest=volume/'anomalous-captures';dest.mkdir(exist_ok=True)
 def remote(code):return subprocess.check_output([cfg['python'],cfg['ssh_helper'],'python3 -c '+shlex.quote(code)],text=True,timeout=180)
 with (dest/'mirror.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  jobs=json.loads(remote("import json;from pathlib import Path;print(json.dumps([j for p in Path('/Users/ufo-field/ufo-field/capture-station/private/internet-archive/jobs').glob('*.json') if (j:=json.loads(p.read_text())).get('verified_at') and j.get('state') in ('retaining','cleaned')]))"))
  state=dict(started=time.time(),total=len(jobs),verified=[],errors=[])
  for job in jobs:
   state.update(current=job['id'],phase='copying');save(dest/'status.json',state)
   try:
    receipt=mirror(job,dest)
    code="""import json,re
from pathlib import Path
sid=SID;receipt=RECEIPT
if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Invalid session')
p=Path('/Users/ufo-field/ufo-field/capture-station/private/internet-archive/jobs')/(sid+'.json');j=json.loads(p.read_text())
expected=[{k:e[k] for k in ('name','bytes','sha256')} for e in j['files']]
if not j.get('verified_at') or j['identifier']!=receipt['identifier'] or expected!=receipt['files']:raise ValueError('Upload revision changed')
p=Path('/Volumes/UFO-Field/sessions')/sid/'archive-copy.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(receipt));t.replace(p)
""".replace('SID',repr(job['id'])).replace('RECEIPT',repr(receipt))
    remote(code);state['verified'].append(job['id'])
   except Exception as exc:state['errors'].append(dict(session=job['id'],error=str(exc)))
   save(dest/'status.json',state)
  state.update(phase='retry_pending' if state['errors'] else 'complete',finished=time.time(),current=None);save(dest/'status.json',state)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args();run(json.loads(Path(args.config).read_text()))
