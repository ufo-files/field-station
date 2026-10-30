"""Station-side evaluated activation, native checkpoint continuity, and rollback."""
import argparse,fcntl,hashlib,json,os,subprocess,sys,time
from pathlib import Path
APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP/'uap-lab/recognition'))
from crop_client import CropClassifier
CONFIG=APP/'uap-lab/recognition/config.json'

def read(p):return json.loads(Path(p).read_text())
def save(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp')
 with tmp.open('w') as f:json.dump(d,f);f.flush();os.fsync(f.fileno())
 tmp.replace(p)

def restart_recognition():
 job='gui/'+str(os.getuid())+'/com.ufo-files.field.recognition'
 if subprocess.run(['launchctl','print',job],capture_output=True).returncode==0:
  # Let the supervisor forward TERM and wait for the child's durable checkpoint.
  subprocess.run(['launchctl','kill','SIGTERM',job],check=True)
 else:
  subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(Path.home()/'Library/LaunchAgents/com.ufo-files.field.recognition.plist')],check=True)

def status():
 cfg=read(CONFIG);policy=read(cfg['policy']);state=read(Path(cfg['spool']).parent/'uap-lab/recognition/status.json')
 return dict(version=policy['version'],package=str(Path(cfg['model']).with_suffix('.mlpackage')),policy=cfg['policy'],health={k:state.get(k) for k in ('model','last_sequence','generation','latency_seconds','backlog_frames','error','updated_epoch')})

def prepare(folder):
 folder=Path(folder);report=read(folder/'promotion-evaluation.json');policy=read(folder/'candidate-policy.json');cfg=read(CONFIG);baseline=read(cfg['policy'])
 if not report.get('passed') or report['candidate_version']!=policy['version'] or report['baseline_version']!=baseline['version']:raise ValueError('Candidate is not approved against the active baseline')
 compiled=folder/'candidate.mlmodelc'
 if not compiled.exists():subprocess.run([str(APP/'migration-work/fast-recognition/compile_model'),str(folder/'candidate.mlpackage'),str(compiled)],check=True,timeout=300,capture_output=True)
 probe=read(folder/'runtime-probe.json');images=[]
 for row in probe:
  p=folder/row['image']
  if p.is_symlink() or not p.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe runtime probe')
  images.append(p.read_bytes())
 if not images:raise ValueError('Missing native runtime probe')
 with CropClassifier(cfg['worker'],compiled,policy['version'],timeout=60) as worker:new=worker.predict(images)
 with CropClassifier(cfg['worker'],cfg['model'],baseline['version'],timeout=60) as worker:old=worker.predict(images)
 if any(r.get('error') for r in new+old):raise ValueError('Runtime probe failed')
 drift=max(abs(float(actual['scores'].get(label,0))-float(score)) for row,actual in zip(probe,new) for label,score in row['scores'].items())
 if drift>.03:raise ValueError('Station runtime predictions differ from evaluation')
 old_times=sorted(r['seconds'] for r in old);new_times=sorted(r['seconds'] for r in new);i=max(0,int(len(new)*.95)-1)
 if new_times[i]>max(.05,old_times[i]*1.5):raise ValueError('Candidate inference latency regressed')
 result=dict(ready=True,epoch=time.time(),max_score_drift=drift,baseline_p95_seconds=old_times[i],candidate_p95_seconds=new_times[i],candidate_version=policy['version'])
 save(folder/'previous-recognition-config.json',cfg);save(folder/'station-probe.json',result);return result

def activate(folder):
 folder=Path(folder);cfg=read(CONFIG);policy=read(folder/'candidate-policy.json');report=read(folder/'promotion-evaluation.json');probe=read(folder/'station-probe.json')
 if not report.get('passed') or not probe.get('ready') or probe['candidate_version']!=policy['version'] or report['baseline_version']!=read(cfg['policy'])['version']:raise ValueError('Activation preconditions changed')
 save(folder/'previous-recognition-config.json',cfg)
 report_path=folder/'promotion-evaluation.json'
 cfg.update(model=str(folder/'candidate.mlmodelc'),policy=str(folder/'candidate-policy.json'),model_transition=dict(from_version=report['baseline_version'],to_version=policy['version'],evaluation_path=str(report_path),evaluation_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest()))
 save(CONFIG,cfg);restart_recognition()
 save(folder/'activation.json',dict(phase='monitoring',epoch=time.time(),version=policy['version']));return dict(phase='monitoring',version=policy['version'])

def rollback(folder):
 folder=Path(folder);old=read(folder/'previous-recognition-config.json');current=read(CONFIG);previous_version=read(old['policy'])['version'];current_version=read(current['policy'])['version']
 if current_version==previous_version:return dict(phase='already_rolled_back')
 if current_version!=read(folder/'candidate-policy.json')['version']:raise ValueError('A different deployment is active; refusing rollback')
 report=folder/'rollback-evaluation.json';save(report,dict(passed=True,kind='rollback_to_previous_runtime',baseline_version=current_version,candidate_version=previous_version,reason='Candidate health verification failed'))
 old['model_transition']=dict(from_version=current_version,to_version=previous_version,evaluation_path=str(report),evaluation_sha256=hashlib.sha256(report.read_bytes()).hexdigest());save(CONFIG,old)
 restart_recognition();save(folder/'activation.json',dict(phase='rolled_back',epoch=time.time(),version=previous_version));return dict(phase='rolled_back',version=previous_version)
def release(folder,metadata):
 folder=Path(folder);policy=read(folder/'candidate-policy.json');report=read(folder/'promotion-evaluation.json');activation=read(folder/'activation.json')
 if metadata['version']!=policy['version'] or metadata['previous_version']!=report['baseline_version'] or not report.get('passed') or activation['phase'] not in ('monitoring','deployed'):raise ValueError('Release is not an evaluated deployment')
 cfg=read(CONFIG);target=Path(cfg['spool']).parent/'notifications/model-releases'/policy['version']/'release.json'
 if target.exists():notice=read(target)
 else:
  current=status();health=current['health']
  if current['version']!=policy['version'] or health.get('model')!=policy['version'] or health.get('error') or time.time()-float(health.get('updated_epoch') or 0)>30:raise ValueError('Release is not healthy and active')
  notice=dict(metadata,state='deployed',health_verified=True);save(target,notice)
 active=target.parent.parent.parent/'active-model-release.json'
 if not active.exists() or read(active)['deployed_epoch']<=notice['deployed_epoch']:save(active,notice)
 save(folder/'activation.json',dict(activation,phase='deployed'));return dict(queued=True,version=policy['version'])

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['status','prepare','activate','rollback','release']);p.add_argument('--folder',type=Path);p.add_argument('--metadata');a=p.parse_args()
 (APP/'auto-training').mkdir(exist_ok=True)
 with (APP/'auto-training/deployment.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  print(json.dumps(status() if a.action=='status' else release(a.folder,json.loads(a.metadata)) if a.action=='release' else globals()[a.action](a.folder)))
