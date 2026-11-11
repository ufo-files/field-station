"""Automatic shared, fresh random 500-image evaluation; never trains a model."""
import argparse,fcntl,hashlib,json,random,secrets,shutil,subprocess,sys,time,uuid
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image
from worker import read,save,model_folder

def choose(rows,count=500,seed=None):
 pool=[r for r in rows if r.get('human_confirmed') and r['label'] in ('anomalous','not_anomalous')]
 if len(pool)<count:raise ValueError('Fewer than 500 human-reviewed images available')
 seed=secrets.randbits(128) if seed is None else seed
 return random.Random(seed).sample(pool,count),str(seed)

def experimental_models(config):
 models={}
 for lane,key in [('experimental','experimental_root'),('hybrid','hybrid_root'),('machine','machine_root')]:
  if not config.get(key):continue
  state=read(Path(config[key])/'status.json',{})
  if state.get('shadow_folder') and not state.get('shadow_seed_only',True):models[lane]=Path(state['shadow_folder'])
 return models

def cycle(config,force=False):
 root=Path(config['root']);human_root=Path(config['human_root']);code=Path(config['code'])
 if not Path('/Volumes/UFO-Work').is_mount() or not root.resolve().is_relative_to('/Volumes/UFO-Work'):raise ValueError('HQ external volume unavailable')
 root.mkdir(parents=True,exist_ok=True)
 cascade=read(human_root/'cascade-status.json',{})
 if not force and cascade.get('phase') in ('preparing','training','activation_pending','evaluating','evaluation_retry_pending','publishing','publication_retry_pending'):return
 with (root/'worker.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  human_state=read(human_root/'status.json',{});human=model_folder(human_root,human_state['active_version']);models={'human':human};versions={}
  models.update(experimental_models(config))
  for lane,folder in models.items():versions[lane]=read(folder/'candidate-policy.json')['version']
  previous=read(root/'status.json',{})
  if not force and previous.get('state')=='complete' and previous.get('versions')==versions:
   sync(config);return
  run=root/'runs'/uuid.uuid4().hex;run.mkdir(parents=True);(run/'images').mkdir()
  save(root/'status.json',dict(state='evaluating',versions=versions,run=str(run),started_epoch=time.time()))
  try:
   dataset=read(human/'dataset.json');rows,seed=choose(dataset['samples']);samples=[];images=[]
   for i,row in enumerate(rows):
    source=human/row['image']
    if not source.resolve().is_relative_to(human.resolve()) or source.is_symlink():raise ValueError('Unsafe benchmark source')
    with Image.open(source) as im:
     im=im.convert('RGB');digest=hashlib.sha256(f'{im.width}x{im.height}:RGB:'.encode()+im.tobytes()).hexdigest()
    if digest!=row['pixel_sha256']:raise ValueError('Benchmark source checksum mismatch')
    raw=source.read_bytes();name='images/'+str(i)+'.png';(run/name).write_bytes(raw);images.append(raw);samples.append(dict(row,image=name))
   sample_id=hashlib.sha256(json.dumps([(r['origin'],r['pixel_sha256'],r['label']) for r in samples]).encode()).hexdigest()
   save(run/'sample.json',dict(id=sample_id,seed=seed,count=500,source_dataset=dataset['fingerprint'],samples=samples,kind='random_reviewed_training_sample'))
   sys.path[:0]=[str(code/'uap-lab/auto_training'),str(code/'uap-lab/recognition'),str(code/'uap-lab')]
   from crop_client import CropClassifier
   from model_test_worker import score
   tools=human_root/'tools';lanes={}
   for lane,folder in models.items():
    policy=read(folder/'candidate-policy.json');version=policy['version'];compiled=root/'compiled'/(version+'.mlmodelc');compiled.parent.mkdir(exist_ok=True)
    if not compiled.exists():subprocess.run([str(tools/'compile_model'),str(folder/'candidate.mlpackage'),str(compiled)],check=True,capture_output=True,timeout=300)
    predictions=[]
    with CropClassifier(tools/'crop_worker',compiled,version,timeout=120) as classifier:
     for start in range(0,len(images),32):predictions.extend(classifier.predict(images[start:start+32]))
    result=score(samples,predictions,policy);save(run/(lane+'-result.json'),result)
    c=result['per_class']['anomalous'];fp=c['fp'];tp=c['tp'];fn=c['fn'];tn=500-fp-tp-fn
    lanes[lane]=dict(accuracy=result['accuracy'],false_positive_rate=fp/(fp+tn) if fp+tn else None,recall=tp/(tp+fn) if tp+fn else None,tp=tp,fp=fp,tn=tn,fn=fn)
   epoch=time.time();point=dict(epoch=epoch,day=datetime.fromtimestamp(epoch,ZoneInfo('America/Los_Angeles')).date().isoformat(),count=500,sample_id=sample_id,cascade_id=config.get('cascade_id'),lanes=lanes,**{lane+'_version':version for lane,version in versions.items()})
   save(run/'result.json',point);history=read(root/'history.json',dict(points=[]));history['points'].append(point);history.update(updated_epoch=epoch,mode='random_reviewed_training_sample',scope='Fresh random 500 reviewed training images per run; all available models use the same images. Training-fit comparison, not unseen-footage accuracy.',seed_only=len(models)==1,phase='complete',available_lanes=list(models))
   save(root/'history.json',history);save(root/'status.json',dict(state='complete',versions=versions,run=str(run),sample_id=sample_id,finished_epoch=epoch,cascade_id=config.get('cascade_id')));sync(config)
  except Exception as exc:
   save(root/'status.json',dict(state='retry_pending',versions=versions,run=str(run),error=str(exc),updated_epoch=time.time()));raise

def sync(config):
 from comparison import publish
 publish(Path(config['hybrid_root']),config['ssh_helper'])

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--force',action='store_true');a=p.parse_args();cycle(read(a.config),a.force)
