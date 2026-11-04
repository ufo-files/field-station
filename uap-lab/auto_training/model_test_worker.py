"""Evaluate saved models without calibration, training, or promotion."""
import argparse,fcntl,hashlib,json,math,shlex,shutil,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from model_tests import read,save

def catalog(root):
 current=read(root/'status.json',{});active=current.get('active_version');models=[]
 writing=Path(current.get('run_directory','')).name if current.get('phase') in ('training','evaluating','deploying','preparing','snapshotting') else None
 for p in (root/'runs').glob('*/candidate-policy.json'):
  folder=p.parent
  if folder.name==writing:continue
  package=next((folder/n for n in ('candidate.mlpackage','proposed.mlpackage') if (folder/n).is_dir()),None)
  if not package:continue
  try:policy=read(p);outcome=read(folder/'run-outcome.json',{})
  except (ValueError,OSError):continue
  models.append(dict(id=folder.name,version=policy['version'],created_epoch=p.stat().st_mtime,active=policy['version']==active,training_result=outcome.get('phase','saved'),reviewed_frames=outcome.get('examples'),package=package.name))
 return sorted(models,key=lambda m:-m['created_epoch'])

def benchmark(root,models):
 dest=root/'model-tests/benchmark';existing=read(dest/'manifest.json')
 if existing:return existing
 from training_benchmark import select
 from PIL import Image
 for model in models:
  folder=root/'runs'/model['id']
  if not (folder/'training-benchmark.json').is_file():continue
  dataset=read(folder/'dataset.json')
  if set(dataset['classes'])!={'anomalous','not_anomalous'}:continue
  rows,meta=select(dataset,folder)
  if len(rows)!=500:continue
  copied=[]
  for i,row in enumerate(rows):
   source=folder/row['image']
   if source.is_symlink() or not source.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe benchmark image')
   with Image.open(source) as im:
    im=im.convert('RGB');pixel=hashlib.sha256(f'{im.width}x{im.height}:RGB:'.encode()+im.tobytes()).hexdigest()
   if pixel!=row['pixel_sha256']:raise ValueError('Benchmark image checksum changed')
   name=f'images/{i:04d}.png';target=dest/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
   copied.append(dict(row,image=name,file_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
  identity=hashlib.sha256(json.dumps(copied,sort_keys=True).encode()).hexdigest()
  value=dict(id=identity,count=500,source_run=model['id'],source=meta,rows=copied);save(dest/'manifest.json',value);return value
 raise ValueError('No complete existing 500-frame training benchmark is available')

def score(rows,results,policy):
 from binary_decision import decide
 from training_policy import summarize
 if len(rows)!=len(results):raise ValueError('Missing benchmark predictions')
 predictions=[]
 for row,result in zip(rows,results):
  if result.get('error'):raise ValueError('Model inference failed: '+str(result['error']))
  scores=result.get('scores',{});probability=scores.get('anomalous')
  if not isinstance(probability,(int,float)) or not math.isfinite(probability) or not 0<=probability<=1:raise ValueError('Invalid anomaly score')
  label=decide(dict(anomalous=probability,not_anomalous=1-probability),policy['thresholds']['anomalous'],max(row['native_width'],row['native_height'])>=policy.get('minimum_native_size',8))
  predictions.append(dict(origin=row['origin'],group=row['group'],truth=row['label'],label=label,score=probability))
 metrics=summarize(predictions,['anomalous','not_anomalous']);correct=sum(p['truth']==p['label'] for p in predictions)
 return dict(metrics,correct=correct,accuracy=correct/len(rows),decision_rule='anomalous-at-threshold-otherwise-not-anomalous')

def evaluate(root,model,sample):
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
 from crop_client import CropClassifier
 folder=root/'runs'/model['id'];policy=read(folder/'candidate-policy.json');package=folder/model['package']
 # Dedicated compilation cache cannot collide with a training run's mutable cache.
 h=hashlib.sha256(json.dumps(policy,sort_keys=True).encode())
 for p in sorted(package.rglob('*')):
  if p.is_file():h.update(str(p.relative_to(package)).encode());h.update(p.read_bytes())
 identity=h.hexdigest();tools=root/'tools';compiled=root/'model-tests/compiled'/(identity+'.mlmodelc');compiled.parent.mkdir(parents=True,exist_ok=True)
 if not compiled.exists():subprocess.run([str(tools/'compile_model'),str(package),str(compiled)],capture_output=True,check=True,timeout=300)
 images=[]
 for row in sample['rows']:
  data=(root/'model-tests/benchmark'/row['image']).read_bytes()
  if hashlib.sha256(data).hexdigest()!=row['file_sha256']:raise ValueError('Pinned benchmark image changed')
  images.append(data)
 with CropClassifier(tools/'crop_worker',compiled,identity,timeout=120) as worker:results=worker.predict(images)
 return dict(score(sample['rows'],results,policy),model_fingerprint=identity,model_version=policy['version'],benchmark_id=sample['id'])

def cycle(cfg):
 root=Path(cfg['root']);work=root/'model-tests';work.mkdir(exist_ok=True)
 with (work/'worker.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  def rpc(action,value=None):
   args=[cfg['remote_python'],cfg['remote_app']+'/uap-lab/model_tests.py','--data',cfg['remote_lab'],action]
   if value is not None:args+=['--json',json.dumps(value)]
   return json.loads(subprocess.check_output([*cfg['ssh_command'],shlex.join(args)],text=True,timeout=120))
  models=catalog(root);sample=benchmark(root,models)
  rpc('catalog',dict(models=models,benchmark={k:sample[k] for k in ('id','count','source_run')},updated_epoch=time.time()))
  jobs=rpc('pending')
  if not jobs:return
  job=jobs[0];job.update(state='running',started_epoch=time.time(),error=None);rpc('update',job)
  try:
   if job['benchmark_id']!=sample['id']:raise ValueError('Requested sample no longer available')
   model=next((m for m in models if m['id']==job['model_id']),None)
   if model is None:raise ValueError('Saved model is unavailable')
   result=evaluate(root,model,sample);save(work/'results'/(job['id']+'.json'),result)
   # Detailed predictions stay on the archive SSD, not in every table refresh.
   job.update(state='complete',result={k:v for k,v in result.items() if k!='predictions'})
  except Exception as exc:job.update(state='failed',error=str(exc))
  job['finished_epoch']=time.time();rpc('update',job)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();cycle(read(Path(a.config)))
