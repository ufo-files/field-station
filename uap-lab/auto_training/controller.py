"""Scheduled review-driven training with immutable datasets and guarded promotion."""
import argparse,fcntl,hashlib,json,os,re,shlex,subprocess,sys,tarfile,time
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
  self.c=cfg;self.root=Path(cfg['root']);self.app=cfg['remote_app'];self.python=cfg['remote_python'];self.code=Path(__file__).resolve().parent;self.state=read(self.root/'status.json',{});self.recipe=hashlib.sha256(b''.join((self.code/name).read_bytes() for name in ('train_candidate.py','training_policy.py','evaluate_candidate.py','native_feature_worker.swift','refine_candidate.py','dataset.py'))).hexdigest()
 def remote(self,args,**kwargs):
  return subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',self.c['host'],shlex.join(map(str,args))],check=True,**kwargs)
 def rpc(self,script,*args):
  return json.loads(self.remote([self.python,self.app+'/uap-lab/auto_training/'+script,*args],capture_output=True,text=True,timeout=360).stdout)
 def mark(self,phase,**fields):
  if 'completed_fingerprint' in fields:fields['completed_recipe']=self.recipe
  self.state.update(phase=phase,updated_epoch=time.time(),**fields);save(self.root/'status.json',self.state)
  try:self.remote([self.python,self.app+'/uap-lab/auto_training/manual_training.py','progress','--json',json.dumps(dict(phase=phase,reason=self.state.get('reason')))],capture_output=True,text=True,timeout=10)
  except Exception:pass # Status delivery must never invalidate an evaluated model.
 def snapshot(self):
  return self.rpc('snapshot.py','--lab',self.c['remote_lab'],'--out',self.app+'/auto-training/exports')
 def reviews_still_valid(self,fp,reviews):
  current=self.snapshot()
  if current['fingerprint']==fp:return True
  if not hasattr(self,'provisional_slot') and not hasattr(self,'manual_request_id'):return False
  from provisional import compatible_reviews
  fresh=current['fingerprint']
  if not re.fullmatch('[a-f0-9]{64}',fresh):raise ValueError('Invalid review snapshot')
  newest=json.loads(self.remote(['cat',self.app+'/auto-training/exports/'+fresh+'/reviews.json'],capture_output=True,text=True,timeout=30).stdout)
  return compatible_reviews(read(reviews/'reviews.json')['samples'],newest['samples'])
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
 def notify_release(self):
  pending=self.state.get('pending_release')
  if not pending:return
  self.rpc('deploy.py','release','--folder',self.state['remote_candidate'],'--metadata',json.dumps(pending))
  self.mark(self.state['phase'],pending_release=None,release_notice_queued_epoch=time.time())
 def tick(self):
  self.notify_release();self.recover();snapshot=self.snapshot();fp=snapshot['fingerprint']
  if not re.fullmatch('[a-f0-9]{64}',fp):raise ValueError('Invalid snapshot identity')
  if not hasattr(self,'provisional_slot') and not hasattr(self,'manual_request_id') and fp==self.state.get('completed_fingerprint') and self.recipe==self.state.get('completed_recipe'):return
  self.mark('snapshot',fingerprint=fp,examples=snapshot['examples'],reason=None,training_recipe=self.recipe)
  reviews=self.root/'reviews'/fp
  if not (reviews/'reviews.json').exists():self.download(self.app+'/auto-training/exports/'+fp,['reviews.json','images'],reviews)
  from collections import Counter
  self.mark('building',labels=dict(Counter(r['label'] for r in read(reviews/'reviews.json')['samples'])))
  run_key=fp+self.recipe+(str(self.c['provisional']['start_epoch'])+':'+str(self.provisional_slot) if hasattr(self,'provisional_slot') else '')+(':manual:'+self.manual_request_id if hasattr(self,'manual_request_id') else '')
  run_id=hashlib.sha256(run_key.encode()).hexdigest();folder=self.root/'runs'/run_id
  if not (folder/'dataset.json').exists():
   # An interrupted build cannot be mistaken for a complete immutable dataset.
   if folder.exists():folder.rename(folder.with_name(run_id+'.incomplete.'+str(time.time_ns())))
   built=build(self.root/'baseline/dataset-001',reviews,folder,self.root/'split-ledger.json')
   built.update(training_recipe=self.recipe,fingerprint=hashlib.sha256((built['fingerprint']+run_key).encode()).hexdigest());save(folder/'dataset.json',built)
  dataset=read(folder/'dataset.json')
  self.state['deferred_labels']=dataset.get('deferred',[])
  if dataset['blockers']:
   self.mark('waiting_for_data',reason=dataset['blockers'],completed_fingerprint=fp);return
  self.mark('training',candidate_version=dataset['fingerprint'],run_directory=str(folder))
  if not (folder/'candidate-policy.json').exists():self.run_script('train_candidate.py',['--folder',folder,'--lock',self.root/'training.lock'],folder)
  active=self.rpc('deploy.py','status');baseline=self.root/'incumbents'/active['version']
  if not (baseline/'candidate-policy.json').exists():
   # Package and policy may have different names/directories; normalize locally.
   for source,name in ((active['package'],'candidate.mlpackage'),(active['policy'],'candidate-policy.json')):
    p=Path(source);self.download(str(p.parent),[p.name],baseline)
    if p.name!=name:(baseline/p.name).rename(baseline/name)
  weights=baseline/'candidate-weights.pt'
  if not weights.exists():self.download(str(Path(active['package']).parent),['candidate-weights.pt'],baseline)
  self.mark('refining_class_corrections',baseline_version=active['version'],active_version=active['version'])
  try:self.run_script('refine_candidate.py',['--folder',folder,'--baseline',baseline],folder)
  except subprocess.CalledProcessError:
   decision=read(folder/'refinement-decision.json',{})
   if decision.get('state')!='waiting_for_data':raise
   self.mark('waiting_for_data',reason=decision['reason'],completed_fingerprint=fp,active_version=active['version']);return
  self.mark('evaluating',baseline_version=active['version'])
  self.run_script('evaluate_candidate.py',['--folder',folder,'--baseline-package',baseline/'candidate.mlpackage','--baseline-policy',baseline/'candidate-policy.json'],folder)
  report=read(folder/'promotion-evaluation.json')
  if not self.reviews_still_valid(fp,reviews):
   self.mark('superseded',reason='New or corrected reviews arrived during training',completed_fingerprint=fp);return
  if not report['passed']:
   self.mark('rejected',reason=report['reasons'],completed_fingerprint=fp);return
  if (hasattr(self,'provisional_slot') or hasattr(self,'manual_request_id')) and fp==self.state.get('deployed_fingerprint') and self.recipe==self.state.get('deployed_recipe'):
   self.mark('validated_unchanged',reason='Retraining validated; labels and recipe unchanged, retaining the active model',completed_fingerprint=fp,active_version=active['version']);return
  remote=self.app+'/auto-training/candidates/'+dataset['fingerprint'];archive=self.root/'candidate.tar.gz'
  files=['candidate.mlpackage','candidate-weights.pt','candidate-policy.json','promotion-evaluation.json','runtime-probe.json']+[r['image'] for r in read(folder/'runtime-probe.json')]
  with tarfile.open(archive,'w:gz') as tar:
   for name in dict.fromkeys(files):tar.add(folder/name,arcname=name)
  self.remote(['mkdir','-p',remote],timeout=30)
  with archive.open('rb') as f:self.remote(['tar','-xzf','-','-C',remote],stdin=f,timeout=300)
  archive.unlink();self.rpc('deploy.py','prepare','--folder',remote)
  if not self.reviews_still_valid(fp,reviews):
   self.mark('superseded',reason='Reviews changed before activation',completed_fingerprint=fp);return
  self.mark('activating',remote_candidate=remote)
  try:
   self.rpc('deploy.py','activate','--folder',remote)
   self.monitor(remote,dataset['fingerprint'],active['health'])
  except Exception:
   self.rpc('deploy.py','rollback','--folder',remote)
   self.mark('rolled_back',completed_fingerprint=fp,reason='Activation or health check failed');raise
  self.mark('deployed',deployed_fingerprint=fp,deployed_recipe=self.recipe,active_version=dataset['fingerprint'],completed_fingerprint=fp,deployed_epoch=time.time(),reason=None,pending_release=dict(version=dataset['fingerprint'],previous_version=active['version'],labels=self.state['labels'],deployed_epoch=time.time()))
  self.notify_release()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();c=Controller(read(a.config));c.root.mkdir(parents=True,exist_ok=True)
 with (c.root/'controller.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:sys.exit(0)
  manual={}
  try:
   manual=c.rpc('manual_training.py','claim')
   if manual:
    c.manual_request_id=manual['id'];c.tick()
   else:
    from provisional import tick
    tick(c)
  except Exception as exc:
   if c.state.get('pending_release'):c.mark(c.state['phase'],notification_error=str(exc))
   elif c.state.get('phase') not in ('activating','rolled_back'):c.mark('error',reason=str(exc))
   raise
  finally:
   if manual:
    c.rpc('manual_training.py','finish','--id',manual['id'],'--json',json.dumps(dict(phase=c.state.get('phase','error'),reason=c.state.get('reason'))))
