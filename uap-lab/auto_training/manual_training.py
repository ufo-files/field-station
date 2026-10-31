"""Durable web requests consumed by the existing serialized training controller."""
import argparse,fcntl,json,time,uuid
from pathlib import Path
APP=Path(__file__).resolve().parents[2]
BUSY={'snapshot','building','training','evaluating','activating','refining_class_corrections'}
class Control:
 def __init__(self,root=None):
  self.root=Path(root or APP/'auto-training');self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'web-training.json'
 def transaction(self,change=None):
  with (self.root/'web-training.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   try:state=json.loads(self.path.read_text())
   except (OSError,ValueError):state={}
   result=change(state) if change else None
   if change:
    temp=self.path.with_suffix('.tmp-'+uuid.uuid4().hex);temp.write_text(json.dumps(state));temp.replace(self.path)
   return result if change else state
 def present(self,state):
  request=state.get('request',{});progress=state.get('progress',{});phase=progress.get('phase','idle')
  pending=request.get('state') in ('queued','running')
  if request.get('state')=='queued':phase='queued'
  elif request.get('state')=='running' and phase not in BUSY:phase='starting'
  busy=pending or (phase in BUSY and time.time()-progress.get('updated_epoch',0)<7200)
  return dict(phase=phase,busy=busy,request_id=request.get('id'),requested_epoch=request.get('requested_epoch'),updated_epoch=progress.get('updated_epoch'),reason=progress.get('reason'))
 def status(self):return self.present(self.transaction())
 def request(self):
  def change(state):
   if not self.present(state)['busy']:state['request']=dict(id=uuid.uuid4().hex,state='queued',requested_epoch=time.time(),source='web')
   return self.present(state)
  return self.transaction(change)
 def claim(self):
  def change(state):
   request=state.get('request',{})
   if request.get('state') not in ('queued','running'):return {}
   request.update(state='running',started_epoch=time.time());state['request']=request;return request
  return self.transaction(change)
 def progress(self,value):
  def change(state):state['progress']=dict(phase=value['phase'],updated_epoch=time.time(),reason=value.get('reason'));return self.present(state)
  return self.transaction(change)
 def finish(self,key,value):
  def change(state):
   if state.get('request',{}).get('id')!=key:raise ValueError('Training request changed')
   state['request'].update(state='complete',finished_epoch=time.time());state['progress']=dict(phase=value['phase'],reason=value.get('reason'),updated_epoch=time.time());return self.present(state)
  return self.transaction(change)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['status','claim','progress','finish']);p.add_argument('--json',default='{}');p.add_argument('--id');a=p.parse_args();c=Control();value=json.loads(a.json)
 print(json.dumps(c.finish(a.id,value) if a.action=='finish' else c.progress(value) if a.action=='progress' else getattr(c,a.action)()))
