"""Authorized hourly cleanup with service leases, receipts, and retained labels."""
import argparse,collections,contextlib,fcntl,json,os,subprocess,sys,time
from pathlib import Path
APP=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(APP/'field-archive'),str(APP/'uap-lab')]
from provisional import slot
from retention import read,save,cycle

TERMINAL={'accepted_by_mail','submitting','uncertain','cancelled','suppressed','expired'}
def expire_alerts(root,cutoff,clear_candidates=False):
 if not clear_candidates:cutoff=min(cutoff,time.time()-48*3600)
 count=0
 for p in root.glob('*/event.json'):
  event=read(p,{});receipt=p.parent/'delivery.json';previous=read(receipt,{})
  if event.get('created_epoch',float('inf'))>cutoff or previous.get('state') in TERMINAL:continue
  save(receipt,dict(state='cancelled',reason='Provisional hourly backlog reset',cutoff_epoch=cutoff,updated_epoch=time.time(),previous_delivery=previous));count+=1
 return count

def metrics(root,cutoff):
 outbox=root/'notifications/outbox';delivery=collections.Counter();models=collections.Counter();reviewed=collections.Counter();events=set()
 for p in outbox.glob('*/event.json'):
  e=read(p,{})
  if cutoff-3600<=e.get('created_epoch',0)<=cutoff:
   events.add(e.get('id'));delivery[read(p.parent/'delivery.json',{}).get('state','pending')]+=1;models[e.get('model','unknown')]+=1
 for p in (root/'uap-lab/email-reviews/examples').glob('*/review.json'):
  r=read(p,{})
  if not r.get('deleted') and r.get('event_id') in events:reviewed[r.get('label','unknown')]+=1
 health=read(root/'uap-lab/recognition/status.json',{})
 return dict(window_start=cutoff-3600,window_end=cutoff,candidates=sum(delivery.values()),delivery=dict(delivery),models=dict(models),review_labels=dict(reviewed),reviewed_candidates=sum(reviewed.values()),health={k:health.get(k) for k in ('model','analyzed_frames','classified_proposals','latency_seconds','backlog_frames','error','updated_epoch')})

@contextlib.contextmanager
def lease(path):
 with path.open('a') as f:
  for _ in range(60):
   try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:time.sleep(1)
  else:raise RuntimeError('Service did not release '+str(path))
  yield

def maintenance(hour=None,release=None):
 cfg=read(APP/'auto-training/provisional-config.json');now=time.time()
 if release is None and slot(cfg,now)!=hour:raise ValueError('Outside the authorized provisional hour')
 clear_candidates=False
 root=Path(cfg['station_root'])
 if not os.path.ismount(root) or (root/'.field-station-volume').read_text().strip()!=cfg['station_marker']:raise ValueError('Station SSD identity mismatch')
 if release is not None:
  import re
  if not re.fullmatch('[a-f0-9]{64}',release):raise ValueError('Invalid release version')
  notice=read(root/'notifications/active-model-release.json',{})
  if notice.get('version')!=release or notice.get('state')!='deployed' or not notice.get('health_verified'):raise ValueError('Release is not healthy and active')
  clear_candidates=notice.get('clear_candidate_backlog') is True
  audit=APP/'maintenance/releases'/release
 else:audit=APP/'maintenance/provisional'/str(int(cfg['provisional']['start_epoch']))/str(hour)
 audit.mkdir(parents=True,exist_ok=True)
 # Acquire the retention worker lease before stopping interactive services.
 # A concurrent cleanup can run for minutes; waiting must leave the app online.
 retention_lock=Path(read(APP/'maintenance/retention/config.json')['audit'])/'worker.lock'
 retention_lock.parent.mkdir(parents=True,exist_ok=True)
 with lease(APP/'auto-training/deployment.lock'),lease(retention_lock):
  record=read(audit/'result.json',{})
  if record.get('complete'):return record
  if not record:record=dict(slot=hour,release=release,cutoff_epoch=notice['deployed_epoch'] if release else now,metrics=metrics(root,now))
  save(audit/'result.json',record)
  domain='gui/'+str(os.getuid());stopped=list(record.get('resume_services',[]))
  marker=APP/'run/web-maintenance.json';marker.parent.mkdir(parents=True,exist_ok=True)
  save(marker,dict(phase='cleanup',pid=os.getpid(),started_epoch=time.time()))
  try:
   for role in ('email-alerts','lab','recognition'):
    job=domain+'/com.ufo-files.field.'+role
    if subprocess.run(['launchctl','print',job],capture_output=True).returncode==0:
     if role not in stopped:stopped.append(role)
     record['resume_services']=stopped;save(audit/'result.json',record)
     subprocess.run(['launchctl','bootout',job],check=True,capture_output=True)
   with contextlib.ExitStack() as stack:
    for path in (root/'notifications/outbox/sender.lock',root/'uap-lab/recognition/service.lock'):
     path.parent.mkdir(parents=True,exist_ok=True);stack.enter_context(lease(path))
    # Pin sent review context before clearing queues or advancing raw retention.
    from alert_evidence import preserve
    record['evidence']=preserve(root)
    if record['evidence']['errors']:raise RuntimeError('Candidate evidence could not be preserved; backlog reset cancelled')
    record['cancelled_alerts']=record.get('cancelled_alerts',0)+expire_alerts(root/'notifications/outbox',record['cutoff_epoch'],clear_candidates)
    save(audit/'result.json',record)
    if 'raw' not in record:
     from reset_backlog import reset
     record['raw']=reset(APP,root,audit/'checkpoint');save(audit/'result.json',record)
    record['videos']=cycle(root,audit/'videos',True,provisional_cutoff=record['cutoff_epoch'],candidate_min_age=0 if clear_candidates else 48*3600)
    if record['videos']['errors']:raise RuntimeError('Video cleanup errors: '+str(record['videos']['errors']))
    record.update(cleanup_finished_epoch=time.time());save(audit/'result.json',record)
  finally:
   errors=[]
   for role in reversed(stopped):
    plist=Path.home()/'Library/LaunchAgents'/('com.ufo-files.field.'+role+'.plist')
    for attempt in range(15):
     result=subprocess.run(['launchctl','bootstrap',domain,str(plist)],capture_output=True)
     if result.returncode==0 or subprocess.run(['launchctl','print',domain+'/com.ufo-files.field.'+role],capture_output=True).returncode==0:break
     time.sleep(2)
    else:errors.append(role)
   marker.unlink(missing_ok=True)
   if errors:record.update(complete=False,resume_errors=errors);save(audit/'result.json',record);raise RuntimeError('Failed to resume '+str(errors))
  record.update(complete=True,finished_epoch=time.time(),resume_services=[]);save(audit/'result.json',record)
  return record

if __name__=='__main__':
 p=argparse.ArgumentParser();group=p.add_mutually_exclusive_group(required=True);group.add_argument('--slot',type=int);group.add_argument('--release');a=p.parse_args();print(json.dumps(maintenance(a.slot,a.release)))
