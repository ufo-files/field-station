"""Eligible evidence replication to M6; originals never removed by this worker."""
import errno,fcntl,hashlib,json,os,re,shlex,subprocess,sys,time
from pathlib import Path
from archive_receiver import canonical,validate
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'capture-station'));sys.path.insert(0,str(ROOT/'uap-lab'))
from archive_policy import eligible
from evidence_copy import copy_evidence
DATA=Path(os.environ.get('UAP_LAB_DATA','/Volumes/UFO-Field/uap-lab'))/'archive-transfer'
HELPER=ROOT/'private/m6-ssh.py';SHIM=ROOT/'private/m6-rsync-ssh.py'
PRIVATE=ROOT/'capture-station/private/internet-archive'
SESSIONS=Path(os.environ.get('CAPTURE_DATA','/Volumes/UFO-Field/sessions'))

def read(path,default=None):
 try:return json.loads(path.read_text())
 except FileNotFoundError:return default

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.replace(path)

def inventory(job):
 sid=job['id']
 if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Invalid archive session')
 result={'schema':1,'session_id':sid,'files':[{k:e[k] for k in ('name','bytes','sha256')} for e in job['files']]};validate(result)
 return result

def source(job,entry):
 if entry.get('private_source'):
  if entry['private_source'] not in (job['id']+'-session.json',job['id']+'-manifest.json',job['id']+'-archive-index.json'):raise ValueError('Private configuration is never archive evidence')
  root=PRIVATE;path=root/entry['private_source']
 else:root=SESSIONS/job['id'];path=root/entry['name']
 if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe or missing evidence source')
 if path.stat().st_size!=entry['bytes']:raise ValueError('Evidence size changed since archive inventory')
 return path

def remote(command,index):
 p=subprocess.run([sys.executable,str(HELPER),'python3 ~/ufo-processing/field-archive-receiver.py '+command],input=canonical(index),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
 if p.returncode:raise RuntimeError('M6 archive '+command+' failed: '+p.stderr.decode(errors='replace')[-1200:])
 return json.loads(p.stdout)

def transfer(job):
 index=inventory(job);fingerprint=validate(index);receipt_path=DATA/'receipts'/(job['id']+'.json');previous=read(receipt_path,{})
 if previous.get('fingerprint')==fingerprint:return False
 # Eligibility is rechecked immediately before networking, including manual takeover.
 folder=SESSIONS/job['id'];manifest=read(folder/'manifest.json',{});decision=read(folder/'archive-decision.json',{})
 if not eligible(manifest,decision):return False
 prepared=remote('prepare',index)
 if prepared['state']=='verified':receipt=prepared['receipt']
 else:
  stage=DATA/'staging'/(job['id']+'-'+fingerprint);stage.mkdir(parents=True,exist_ok=True)
  for entry in job['files']:
   original=source(job,entry);dest=stage/entry['name'];dest.parent.mkdir(parents=True,exist_ok=True)
   if dest.exists():continue
   try:os.link(original,dest)
   except OSError as exc:
    if exc.errno!=errno.EXDEV:raise
    copy_evidence(original,dest)
  (stage/'transfer-index.json').write_bytes(canonical(index))
  transport=shlex.join([sys.executable,str(SHIM)])
  args=['/usr/bin/rsync','-rt','--partial','--partial-dir=.rsync-partial','--bwlimit=8192','--timeout=60','-e',transport,str(stage)+'/', 'm6:'+prepared['destination']]
  save(DATA/'status.json',dict(phase='transferring',session_id=job['id'],bytes=sum(e['bytes'] for e in index['files']),updated_epoch=time.time(),bandwidth_limit_KiBps=8192))
  completed=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12*3600)
  if completed.returncode:raise RuntimeError('M6 evidence transfer interrupted: '+completed.stderr.decode(errors='replace')[-1200:])
  receipt=remote('verify',index)
 if receipt.get('fingerprint')!=fingerprint or receipt.get('files')!=index['files']:raise ValueError('M6 receipt does not match original evidence inventory')
 save(receipt_path,receipt);save(DATA/'status.json',dict(phase='verified',session_id=job['id'],fingerprint=fingerprint,updated_epoch=time.time(),originals_retained=True))
 return True

def tick():
 for path in sorted((PRIVATE/'jobs').glob('*.json')):
  job=read(path,{})
  if job.get('state') in ('held_for_review','failed','cleaned'):continue
  if transfer(job):return True
 return False

def main():
 DATA.mkdir(parents=True,exist_ok=True)
 with (DATA/'worker.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  while True:
   try:
    changed=tick()
    if '--once' in sys.argv:break
    if not changed:save(DATA/'status.json',dict(phase='idle',updated_epoch=time.time(),originals_retained=True))
   except Exception as exc:
    save(DATA/'status.json',dict(phase='waiting_retry',error=str(exc),updated_epoch=time.time(),originals_retained=True))
    if '--once' in sys.argv:raise
   time.sleep(30)
if __name__=='__main__':main()
