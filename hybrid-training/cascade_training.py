"""Isolated training snapshots and publication for manual multi-model cycles."""
import ctypes,fcntl,hashlib,json,os,shutil,sys,time
from collections import Counter
from pathlib import Path
from worker import read,save,finish_training
from policy import eligible_pseudo

def copy_image(source,destination):
 destination.parent.mkdir(parents=True,exist_ok=True)
 if source.is_symlink():raise ValueError('Symlink training image')
 if sys.platform=='darwin' and ctypes.CDLL(None).clonefile(os.fsencode(source),os.fsencode(destination),0)==0:return
 shutil.copyfile(source,destination)

def freeze_inputs(cfg,request_id):
 result={};root=Path(cfg['cycle_root'])/request_id;root.mkdir(parents=True,exist_ok=True)
 for lane in ('hybrid','machine'):
  source=Path(cfg['lanes'][lane]['root'])/'corpus/manifest.json';target=root/(lane+'-manifest.json')
  if not target.exists():save(target,read(source,{}))
  result[lane]=str(target)
 return result

def build_snapshot(cfg,cycle,lane):
 settings=cfg['lanes'][lane];root=Path(settings['root']);source=Path(cycle['stable_source']);base=read(source/'dataset.json');recipe=read(root/'recipe.json',{})
 key=hashlib.sha256(json.dumps([cycle['id'],lane,base['fingerprint'],recipe],sort_keys=True).encode()).hexdigest();folder=root/'runs'/key
 if (folder/'dataset.json').exists():return folder
 if folder.exists():folder.rename(folder.with_name(key+'.incomplete.'+str(time.time_ns())))
 (folder/'images').mkdir(parents=True)
 rows=[];sources=[]
 if lane!='machine':
  for row in base['samples']:
   if lane=='experimental' and not row.get('human_confirmed'):continue
   rows.append(dict(row));sources.append(source/row['image'])
 if lane in ('hybrid','machine'):
  corpus=Path(settings['root'])/'corpus';machine_rows=list(read(cycle['inputs'][lane],{}).values())
  if lane=='hybrid':machine_rows=eligible_pseudo(rows,machine_rows)
  held_out={alias for row in rows if row['split']!='train' for alias in row.get('group_aliases',[])}
  for row in machine_rows:
   if row.get('human_confirmed') or row.get('label_source')!='machine':raise ValueError('Human label in machine corpus')
   if lane=='hybrid' and ('generation:'+row['generation'] in held_out or row['generation'] in held_out):continue
   rows.append(dict(origin='machine:'+row['id'],label=row['label'],group='machine:'+row['generation'],pixel_sha256=row['pixel_sha256'],native_width=row['native_width'],native_height=row['native_height'],human_confirmed=False,label_source='machine',input_color_space='RGB',split='train',**({'pseudo_label':True} if lane=='hybrid' else {})))
   sources.append(corpus/row['image'])
 quarantine=[]
 if lane=='machine':
  sys.path.insert(0,str(Path(cfg['code'])/'uap-lab/recognition'))
  from candidate_dataset import group_rows
  rows,quarantine=group_rows([dict(row,source=str(src)) for row,src in zip(rows,sources)])
  sources=[Path(row.pop('source')) for row in rows]
 if {r['label'] for r in rows}!={'anomalous','not_anomalous'}:raise ValueError('Both labeled classes are required')
 for index,(row,src) in enumerate(zip(rows,sources)):
  image='images/'+str(index)+'.png';copy_image(src,folder/image);row['image']=image
 data=dict(base,samples=rows,fingerprint=key,blockers=[],counts=dict(Counter(r['label'] for r in rows)),training_lane={'experimental':'human_experimental','hybrid':'hybrid','machine':'machine_only'}[lane],shadow_only=True,training_strategy=recipe.get('training_strategy','recording_balanced'),cascade_id=cycle['id'],source_dataset=base['fingerprint'],quarantine=quarantine,human_baseline_version=read(source/'candidate-policy.json')['version'],pseudo_labels=sum(not r.get('human_confirmed') and r.get('label_source')=='machine' for r in rows),human_training_counts=dict(Counter(r['label'] for r in rows if r.get('human_confirmed'))))
 if lane=='machine':data.update(evaluation_mode='shared_human_benchmark',fixed_anomaly_threshold=.8,human_training_counts={})
 save(folder/'dataset.json',data);save(folder/'experiment.json',dict(cascade_id=cycle['id'],lane=lane,recipe=recipe,source_model=str(source),created_epoch=time.time()))
 return folder

def train_lane(cfg,cycle,lane):
 root=Path(cfg['lanes'][lane]['root']);root.mkdir(parents=True,exist_ok=True)
 code=Path(cfg['code']);sys.path[:0]=[str(code/'uap-lab/auto_training'),str(code/'uap-lab/recognition'),str(code/'uap-lab')]
 # Serialize against collection and any worker already running before the cascade.
 with (root/'worker.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  folder=build_snapshot(cfg,cycle,lane);state=read(root/'status.json',{})
  state.update(phase='training',training_lane={'experimental':'human_experimental','hybrid':'hybrid','machine':'machine_only'}[lane],run_directory=str(folder),cascade_id=cycle['id'],error=None,baseline_copy=False,reason=None)
  save(root/'status.json',state)
  try:finish_training(root,folder,code,Path(cfg['human_root']),state)
  except Exception as exc:
   state.update(phase='error',error=str(exc),updated_epoch=time.time());save(root/'status.json',state);raise
  result=read(root/'status.json');return dict(version=result['shadow_version'],folder=str(folder),publication=result.get('publication'),publication_error=result.get('publication_error'))

def compare(cfg,cycle):
 from benchmark_worker import cycle as evaluate
 config=read(cfg['comparison_config']);status=read(Path(config['root'])/'status.json',{})
 if status.get('cascade_id')==cycle['id'] and status.get('state')=='complete':return status
 config['cascade_id']=cycle['id'];evaluate(config,force=True)
 status=read(Path(config['root'])/'status.json',{})
 if status.get('state')!='complete' or status.get('cascade_id')!=cycle['id']:raise RuntimeError('Shared evaluation has not completed')
 return status


def retry_publications(cfg,cycle):
 code=Path(cfg['code']);sys.path[:0]=[str(code/'uap-lab/auto_training'),str(code/'uap-lab/recognition'),str(code/'uap-lab')]
 from publish import publish
 errors={}
 for lane,result in cycle['steps'].items():
  if lane=='human' or result.get('state')!='complete' or result.get('publication'):continue
  try:
   root=Path(cfg['lanes'][lane]['root']);result['publication']=publish(root,Path(result['folder']));result.pop('publication_error',None)
   state=read(root/'status.json',{});state['publication']=result['publication'];state.pop('publication_error',None);save(root/'status.json',state)
  except Exception as exc:errors[lane]=str(exc)
 return errors
