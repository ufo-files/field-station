"""Explicit backlog deletion; retain human-reviewed training and evidence."""
import contextlib,fcntl,json,os,shlex,signal,subprocess,sys,time,uuid
from pathlib import Path
APP=Path(__file__).resolve().parents[1]
RUN=APP/'maintenance/backlog-control'
def read(path,default=None):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return default

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(value));temp.replace(path)

def status():
 value=read(RUN/'latest.json',dict(phase='idle'))
 if not value.get('busy') and (RUN/'request.lock').exists():
  with (RUN/'request.lock').open('a') as lock:
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:return dict(phase='clearing',busy=True)
 if value.get('busy'):
  try:os.kill(value['pid'],0)
  except (OSError,KeyError):value.update(busy=False,phase='error',error='Cleanup worker stopped; inspect its audit before retrying.')
 return value

def start():
 RUN.mkdir(parents=True,exist_ok=True)
 with (RUN/'request.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return status()
  request=uuid.uuid4().hex
  with (RUN/'worker.log').open('a') as log:
   child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),request,str(lock.fileno())],pass_fds=(lock.fileno(),),stdout=log,stderr=log,start_new_session=True)
  return dict(busy=True,phase='queued',request_id=request,pid=child.pid)

def stop_orphaned_service(script, grace=10):
 """After bootout, reap only this user's exact service script, never its lock file."""
 script=str(script)
 def matching():
  rows=subprocess.check_output(['ps','-axo','pid=,uid=,command='],text=True).splitlines()
  found=[]
  for row in rows:
   fields=row.strip().split(None,2)
   if len(fields)!=3:continue
   pid,uid,command=fields
   try:args=shlex.split(command)
   except ValueError:continue
   if int(uid)==os.getuid() and len(args)>1 and args[1]==script and int(pid)!=os.getpid():found.append(int(pid))
  return found
 def send(sig):
  for pid in matching():
   try:os.kill(pid,sig)
   except ProcessLookupError:pass
 send(signal.SIGTERM)
 deadline=time.monotonic()+grace
 while matching() and time.monotonic()<deadline:time.sleep(.1)
 send(signal.SIGKILL)
 deadline=time.monotonic()+5
 while matching():
  if time.monotonic()>=deadline:raise RuntimeError('Could not stop recognition process safely')
  time.sleep(.1)

def work(request):
 sys.path.insert(0,str(APP/'uap-lab/auto_training'))
 from provisional_station import lease
 from backlog_reset import reset
 from label_queue import clear_backlog
 env=read(APP/'environment.json');root=Path(env['CAPTURE_VOLUME']);audit=RUN/request
 record=dict(request_id=request,pid=os.getpid(),busy=True,phase='clearing',started_epoch=time.time())
 def update():save(audit/'result.json',record);save(RUN/'latest.json',record)
 update();stopped=[];marker=APP/'run/web-maintenance.json';domain='gui/'+str(os.getuid())
 try:
  if not root.is_mount() or (root/'.field-station-volume').read_text().strip()!=env['CAPTURE_VOLUME_ID']:raise RuntimeError('Station volume identity mismatch')
  retention_config=read(APP/'maintenance/retention/config.json',{})
  retention_lease=lease(Path(retention_config['audit'])/'worker.lock') if retention_config else contextlib.nullcontext()
  with lease(APP/'auto-training/deployment.lock'),retention_lease:
   try:
    for role in ('recognition',):
     label='app.ufo-files.field.'+role
     if subprocess.run(['launchctl','print',domain+'/'+label],capture_output=True).returncode==0:
      subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True,check=True);stopped.append(label)
    stop_orphaned_service(APP/'uap-lab/recognition/recognition_service.py')
    with lease(root/'uap-lab/recognition/service.lock'):
     record['analysis']=reset(APP,root,audit/'checkpoint');update()
    # Only the analysis reset requires the services to be offline. Restore
    # them before the slower, separately locked deletion of review media.
    for label in reversed(stopped):
     r=subprocess.run(['launchctl','bootstrap',domain,str(Path.home()/'Library/LaunchAgents'/(label+'.plist'))],capture_output=True)
     if r.returncode and subprocess.run(['launchctl','print',domain+'/'+label],capture_output=True).returncode:raise RuntimeError('Could not restart '+label)
    stopped.clear();marker.unlink(missing_ok=True)
    record['phase']='deleting';update()
    record['review']=clear_backlog(root/'uap-lab',cutoff=record['started_epoch']);update()
   finally:
    errors=[]
    for label in reversed(stopped):
     for attempt in range(15):
      r=subprocess.run(['launchctl','bootstrap',domain,str(Path.home()/'Library/LaunchAgents'/(label+'.plist'))],capture_output=True)
      if r.returncode==0 or subprocess.run(['launchctl','print',domain+'/'+label],capture_output=True).returncode==0:break
      time.sleep(1)
     else:errors.append(label)
    marker.unlink(missing_ok=True)
    if errors:raise RuntimeError('Could not restart '+', '.join(errors))
  record.update(phase='complete',busy=False,finished_epoch=time.time())
 except Exception as exc:record.update(phase='error',busy=False,error=str(exc),finished_epoch=time.time())
 update()

if __name__=='__main__':work(sys.argv[1])
