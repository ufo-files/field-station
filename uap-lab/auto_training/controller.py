"""Scheduled review-driven training with immutable datasets and guarded promotion."""
import argparse,fcntl,json,os,re,shlex,subprocess,sys,tarfile,time
from pathlib import Path
from dataset import build

def read(p,default=None):
 try:return json.loads(Path(p).read_text())
 except FileNotFoundError:return default

def save(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp')
 with tmp.open('w') as f:json.dump(d,f);f.flush();os.fsync(f.fileno())
 tmp.replace(p)

class Controller:
 def __init__(self,cfg):
  self.c=cfg;self.root=Path(cfg['root']);self.app=cfg['remote_app'];self.python=cfg['remote_python'];self.code=Path(__file__).resolve().parent;self.state=read(self.root/'status.json',{})
 def remote(self,args,**kwargs):
  return subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',self.c['host'],shlex.join(map(str,args))],check=True,**kwargs)
 def rpc(self,script,*args):
  return json.loads(self.remote([self.python,self.app+'/uap-lab/auto_training/'+script,*args],capture_output=True,text=True,timeout=360).stdout)
 def mark(self,phase,**fields):
  self.state.update(phase=phase,updated_epoch=time.time(),**fields);save(self.root/'status.json',self.state)
 def snapshot(self):
  return self.rpc('snapshot.py','--lab',self.c['remote_lab'],'--out',self.app+'/auto-training/exports')
 def download(self,remote,paths,target):
  target.mkdir(parents=True,exist_ok=True);archive=self.root/'download.tar.gz'
  with archive.open('wb') as f:self.remote(['tar','-czf','-','-C',remote,*paths],stdout=f,timeout=300)
  with tarfile.open(archive) as tar:tar.extractall(target,filter='data')
  archive.unlink()
 def run_script(self,script,args,folder):
  with (folder/(script+'.log')).open('a') as log:subprocess.run([self.c['training_python'],str(self.code/script),*map(str,args)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=3600)
 def monitor(self,folder,version,before):
  last=None;deadline=time.monotonic()+120;threshold=max(5,float(before.get('latency_seconds') or 0)+5)
  while time.monotonic()<deadline:
   time.sleep(5)
   health=self.rpc('deploy.py','status')['health'];seq=health.get('last_sequence');fresh=time.time()-float(health.get('updated_epoch') or 0)<15
   if health.get('model')==version and fresh and not health.get('error') and float(health.get('latency_seconds') or 999)<threshold:
    if last is not None and seq is not None and seq>last:return
    last=seq
  raise RuntimeError('Candidate did not demonstrate healthy advancing recognition')
 def recover(self):
  if self.state.get('phase')!='activating':return
  # On uncertain activation or interrupted monitoring, restore the known runtime.
  folder=self.state['remote_candidate'];self.rpc('deploy.py','rollback','--folder',folder)
  self.mark('rolled_back',reason='Interrupted activation recovered',completed_fingerprint=self.state['fingerprint'])
 def tick(self):
  self.recover();snapshot=self.snapshot();fp=snapshot['fingerprint']
  if not re.fullmatch('[a-f0-9]{64}',fp):raise ValueError('Invalid snapshot identity')
  if fp==self.state.get('completed_fingerprint'):return
  self.mark('snapshot',fingerprint=fp,examples=snapshot['examples'],reason=None)
  reviews=self.root/'reviews'/fp
  if not (reviews/'reviews.json').exists():self.download(self.app+'/auto-training/exports/'+fp,['reviews.json','images'],reviews)
  from collections import Counter
  self.mark('building',labels=dict(Counter(r['label'] for r in read(reviews/'reviews.json')['samples'])))
  folder=self.root/'runs'/fp
  if not (folder/'dataset.json').exists():
   # An interrupted build cannot be mistaken for a complete immutable dataset.
   if folder.exists():folder.rename(folder.with_name(fp+'.incomplete.'+str(time.time_ns())))
   build(self.root/'baseline/dataset-001',reviews,folder,self.root/'split-ledger.json')
  dataset=read(folder/'dataset.json')
  if dataset['blockers']:
   self.mark('waiting_for_data',reason=dataset['blockers'],completed_fingerprint=fp);return
  self.mark('training',candidate_version=dataset['fingerprint'])
  if not (folder/'candidate-policy.json').exists():self.run_script('train_candidate.py',['--folder',folder,'--lock',self.root/'training.lock'],folder)
  active=self.rpc('deploy.py','status');baseline=self.root/'incumbents'/active['version']
  if not (baseline/'candidate-policy.json').exists():
   # Package and policy may have different names/directories; normalize locally.
   for source,name in ((active['package'],'candidate.mlpackage'),(active['policy'],'candidate-policy.json')):
    p=Path(source);self.download(str(p.parent),[p.name],baseline)
    if p.name!=name:(baseline/p.name).rename(baseline/name)
  self.mark('evaluating',baseline_version=active['version'])
  self.run_script('evaluate_candidate.py',['--folder',folder,'--baseline-package',baseline/'candidate.mlpackage','--baseline-policy',baseline/'candidate-policy.json'],folder)
  report=read(folder/'promotion-evaluation.json')
  if self.snapshot()['fingerprint']!=fp:
   self.mark('superseded',reason='New or corrected reviews arrived during training',completed_fingerprint=fp);return
  if not report['passed']:
   self.mark('rejected',reason=report['reasons'],completed_fingerprint=fp);return
  remote=self.app+'/auto-training/candidates/'+dataset['fingerprint'];archive=self.root/'candidate.tar.gz'
  files=['candidate.mlpackage','candidate-policy.json','promotion-evaluation.json','runtime-probe.json']+[r['image'] for r in read(folder/'runtime-probe.json')]
  with tarfile.open(archive,'w:gz') as tar:
   for name in dict.fromkeys(files):tar.add(folder/name,arcname=name)
  self.remote(['mkdir','-p',remote],timeout=30)
  with archive.open('rb') as f:self.remote(['tar','-xzf','-','-C',remote],stdin=f,timeout=300)
  archive.unlink();self.rpc('deploy.py','prepare','--folder',remote)
  if self.snapshot()['fingerprint']!=fp:
   self.mark('superseded',reason='Reviews changed before activation',completed_fingerprint=fp);return
  self.mark('activating',remote_candidate=remote)
  try:
   self.rpc('deploy.py','activate','--folder',remote)
   self.monitor(remote,dataset['fingerprint'],active['health'])
  except Exception:
   self.rpc('deploy.py','rollback','--folder',remote)
   self.mark('rolled_back',completed_fingerprint=fp,reason='Activation or health check failed');raise
  self.mark('deployed',completed_fingerprint=fp,deployed_epoch=time.time(),reason=None)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();c=Controller(read(a.config));c.root.mkdir(parents=True,exist_ok=True)
 with (c.root/'controller.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:sys.exit(0)
  try:c.tick()
  except Exception as exc:
   if c.state.get('phase')!='activating':c.mark('error',reason=str(exc))
   raise
