"""Durable requests and results for testing saved models on one shared sample."""
import argparse,fcntl,json,re,time,uuid
from pathlib import Path

def read(path,default=None):
 try:return json.loads(path.read_text())
 except FileNotFoundError:return default

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(value));tmp.replace(path)

def state(data):
 root=Path(data)/'model-tests';catalog=read(root/'catalog.json',dict(models=[],benchmark=None))
 return dict(catalog,models=[dict(m,test=read(root/'requests'/(m['id']+'.json'))) for m in catalog['models']])

def request(data,model_id,benchmark_id):
 root=Path(data)/'model-tests';root.mkdir(parents=True,exist_ok=True)
 with (root/'requests.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  catalog=read(root/'catalog.json',{})
  if not re.fullmatch('[a-f0-9]{64}',str(model_id)) or model_id not in {m['id'] for m in catalog.get('models',[])}:raise ValueError('Saved model is unavailable')
  if benchmark_id!=catalog.get('benchmark',{}).get('id'):raise ValueError('Evaluation sample changed; refresh this page')
  path=root/'requests'/(model_id+'.json');previous=read(path,{})
  if previous.get('state') in ('queued','running'):return previous
  job=dict(id=uuid.uuid4().hex,model_id=model_id,benchmark_id=benchmark_id,state='queued',requested_epoch=time.time())
  save(path,job);return job

def pending(data):
 root=Path(data)/'model-tests/requests'
 return sorted([j for p in root.glob('*.json') if (j:=read(p)).get('state') in ('queued','running')],key=lambda j:j['requested_epoch'])

def update(data,job):
 root=Path(data)/'model-tests';model_id=job['model_id']
 if not re.fullmatch('[a-f0-9]{64}',model_id):raise ValueError('Invalid model')
 with (root/'requests.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);path=root/'requests'/(model_id+'.json');current=read(path,{})
  if current.get('id')!=job['id']:raise ValueError('Test request superseded')
  save(path,job)
  if job['state'] in ('complete','failed'):save(root/'history'/(job['id']+'.json'),job)
 return job

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('action',choices=['catalog','pending','update','request']);p.add_argument('--json');a=p.parse_args();v=json.loads(a.json) if a.json else None
 if a.action=='catalog':save(Path(a.data)/'model-tests/catalog.json',v);result={'saved':True}
 elif a.action=='pending':result=pending(a.data)
 elif a.action=='request':result=request(a.data,v['model_id'],v['benchmark_id'])
 else:result=update(a.data,v)
 print(json.dumps(result))
