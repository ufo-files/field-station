"""HQ-only hybrid self-training. Never activates a field model or modifies a review."""
import argparse,fcntl,hashlib,io,json,os,random,shlex,shutil,sqlite3,subprocess,sys,tarfile,time
from pathlib import Path
from PIL import Image,ImageEnhance
from policy import pseudo_label,eligible_pseudo,score

def read(p,default=None):
 try:return json.loads(Path(p).read_text())
 except FileNotFoundError:return default

def save(p,value):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(p)

def png(image):
 out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()

def model_folder(root,version):
 state=read(root/'status.json',{});current=Path(state.get('run_directory','/nonexistent'))
 if read(current/'candidate-policy.json',{}).get('version')==version:return current
 for p in (root/'runs').glob('*/candidate-policy.json'):
  if read(p,{}).get('version')==version:return p.parent
 raise ValueError('Active human model is not available at HQ')

def finish_training(root,folder,code,human_root,state):
 built=read(folder/'dataset.json');key=built['fingerprint']
 state.update(phase='training');save(root/'status.json',state)
 with (folder/'training.log').open('a') as log:subprocess.run([sys.executable,str(code/'uap-lab/auto_training/train_candidate.py'),'--folder',str(folder),'--lock',str(human_root/'training.lock')],stdout=log,stderr=log,check=True,timeout=21600)
 from crop_client import CropClassifier
 from night_context_calibration import qualify
 tools=human_root/'tools';compiled=tools/(key+'.mlmodelc')
 from native_compile import compile_model
 compile_model(tools/'compile_model',folder/'candidate.mlpackage',compiled)
 if (human_root/'crop-parity-audit.tar').exists():shutil.copyfile(human_root/'crop-parity-audit.tar',root/'crop-parity-audit.tar')
 student_policy=read(folder/'candidate-policy.json')
 if built.get('training_lane')!='machine_only':
  with CropClassifier(tools/'crop_worker',compiled,key,timeout=120) as classifier:student_policy['night_context_confirmation']=qualify(folder,built,classifier,student_policy['thresholds']['anomalous'])
 else:student_policy['night_context_confirmation']=dict(enabled=False,reason='Machine-only model does not calibrate on human labels')
 save(folder/'candidate-policy.json',student_policy)
 state.update(phase='shadow_ready',shadow_folder=str(folder),shadow_version=key,shadow_seed_only=False,trained_epoch=time.time(),human_examples=sum(bool(row.get('human_confirmed')) for row in built['samples']));save(root/'status.json',state)
 try:
  from publish import publish
  state['publication']=publish(root,folder);state.pop('publication_error',None)
 except Exception as exc:state['publication_error']=str(exc)
 save(root/'status.json',state)

def run(c):
 root=Path(c['root']);machine=c.get('lane')=='machine_only';volume=Path('/Volumes/UFO-Work')
 if not volume.is_mount() or not root.resolve().is_relative_to(volume):raise ValueError('HQ external storage unavailable')
 root.mkdir(parents=True,exist_ok=True);(root/'frames').mkdir(exist_ok=True)
 with (root/'worker.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  state=read(root/'status.json',{});state['training_lane']=c.get('lane','hybrid');pool=read(root/'pseudo-labels.json',{});pairs=read(root/'comparisons.json',{})
  code=Path(c['code']);sys.path[:0]=[str(code/'uap-lab/auto_training'),str(code/'uap-lab'),str(code/'uap-lab/recognition')]
  if state.get('shadow_folder') and not (root/'publications'/(state['shadow_version']+'.json')).exists():
   try:
    from publish import publish
    state['publication']=publish(root,Path(state['shadow_folder']));state.pop('publication_error',None)
   except Exception as exc:state['publication_error']=str(exc)
  human_root=Path(c['human_root']);human_state=read(human_root/'status.json');version=human_state['active_version'];human=model_folder(human_root,version)
  pending=Path(state.get('run_directory','/nonexistent'))
  if (pending/'dataset.json').exists() and str(pending)!=state.get('shadow_folder'):
   if human_state.get('phase') in {'snapshot','building','training','evaluating','activating','activation_pending'}:
    state.update(phase='waiting_for_human_training',reason='Hybrid training will retry after the human model run finishes.');save(root/'status.json',state);return
   state.update(error=None,reason='Retrying the saved hybrid training snapshot with a six-hour limit.')
   finish_training(root,pending,code,human_root,state)
   return
  teacher=Path(c['bootstrap_folder']) if machine else human
  if machine and not state.get('shadow_folder'):state['shadow_version']=read(teacher/'candidate-policy.json')['version']
  policy=read(teacher/'candidate-policy.json');dataset=read(human/'dataset.json');human_pixels={r['pixel_sha256'] for r in dataset['samples'] if r.get('human_confirmed')}
  db=sqlite3.connect(Path(c['hq_cache']).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
  try:
   records=[json.loads(r[0]) for r in db.execute('SELECT row FROM objects')];reviewed={r['id'] for r in records if r.get('human_reviewed')};reviewed.update(r[0] for r in db.execute('SELECT object_id FROM decisions'))
  finally:db.close()
  backup=(Path(c['backup'])/'current').resolve();manifest=read(backup/'email-reviews/training-manifest.json',{});truth={r.get('sample_id',r['event_id']):(r['label'],r.get('reviewed_epoch',0)) for r in manifest.get('examples',[]) if r.get('human_confirmed') and not r.get('deleted')}
  reviewed.update(truth)
  for key in list(pool):
   if not machine and (key in reviewed or pool[key]['pixel_sha256'] in human_pixels):pool.pop(key)
  for key,row in pairs.items():
   row['truth']=truth[key][0] if key in truth and truth[key][1]>row.get('scored_epoch',float('inf')) else None
  candidates=[r['id'] for r in records if r['kind']=='detection' and not r.get('human_reviewed') and r['id'] not in reviewed and r['id'] not in pairs]
  random.Random(int(time.time()//300)).shuffle(candidates);candidates=candidates[:200]
  state.update(phase='collecting',error=None,human_version=version,shadow_version=state.get('shadow_version',version),shadow_seed_only=not state.get('shadow_folder'),automatic_switch=False,updated_epoch=time.time())
  save(root/'status.json',state)
  if candidates:
   command=shlex.join(['/Users/ufo-field/ufo-field/venv/bin/python','/Users/ufo-field/ufo-field/uap-lab/hybrid_training_export.py',json.dumps(candidates)])
   raw=subprocess.run(['/usr/bin/python3',c['ssh_helper'],command],capture_output=True,check=True,timeout=120).stdout
   if len(raw)>210*1024**2:raise ValueError('Native crop batch exceeds limit')
   from crop_client import CropClassifier
   from binary_decision import decide
   from night_context import enabled
   tools=human_root/'tools';shadow=Path(state.get('shadow_folder',str(teacher)));shadow_policy=read(shadow/'candidate-policy.json');models=[('human',human,read(human/'candidate-policy.json')),('hybrid',shadow,shadow_policy)]
   batch=[]
   with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
    for row in json.load(tar.extractfile('samples.json')):
     image_raw=tar.extractfile(row['id']+'.png').read()
     if hashlib.sha256(image_raw).hexdigest()!=row['sha256']:raise ValueError('Native crop transfer checksum mismatch')
     image=Image.open(io.BytesIO(image_raw)).convert('RGB');x,y,w,h=row['detection_bounds'];bx,by,bw,bh=row['bounds']
     if x<bx or y<by or x+w>bx+bw or y+h>by+bh:continue
     tight=png(image.crop((x-bx,y-by,x-bx+w,y-by+h)))
     batch.append((row,image_raw,tight,[png(image),png(image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)),png(ImageEnhance.Contrast(image).enhance(1.1))]))
   predictions={}
   for lane,folder,p in models:
    if lane=='hybrid' and p['version']==models[0][2]['version']:
     predictions[lane]=predictions['human'];continue
    compiled=tools/(p['version']+'.mlmodelc')
    if not compiled.exists():subprocess.run([str(tools/'compile_model'),str(folder/'candidate.mlpackage'),str(compiled)],check=True,capture_output=True,timeout=300)
    with CropClassifier(tools/'crop_worker',compiled,p['version'],timeout=120) as classifier:
     values=[]
     for start in range(0,len(batch),32):values.extend(classifier.predict([image for _,_,tight,views in batch[start:start+32] for image in [tight,*views]]))
    if any(r.get('error') for r in values):raise ValueError('Shadow inference failed')
    predictions[lane]=[values[i:i+4] for i in range(0,len(values),4)]
   for i,(row,raw,tight,views) in enumerate(batch):
    labels={}
    for lane,folder,p in models:
     values=predictions[lane][i];label=decide(values[0]['scores'],p['thresholds']['anomalous'],max(row['detection_bounds'][2:])>=p['minimum_native_size'])
     if enabled(p,row['captured_epoch']) and values[1]['scores']['anomalous']<p['night_context_confirmation']['minimum_context_score']:label='not_anomalous'
     labels[lane]=label
    pairs[row['id']]=dict(id=row['id'],scored_epoch=time.time(),generation=row['generation'],captured_epoch=row['captured_epoch'],human=labels['human'],hybrid=labels['hybrid'],human_version=version,hybrid_version=shadow_policy['version'],prospective=not state.get('shadow_seed_only') and row['captured_epoch']>max(human_state.get('deployed_epoch',time.time()),state.get('trained_epoch',time.time())),truth=None)
    proposed=pseudo_label([v['scores'] for v in predictions['human'][i][1:]])
    student=pseudo_label([v['scores'] for v in predictions['hybrid'][i][1:]])
    if machine:proposed=student
    if proposed is None or (not machine and (proposed!=student or row['pixel_sha256'] in human_pixels)):continue
    (root/'frames'/(row['id']+'.png')).write_bytes(raw);pool[row['id']]=dict(row,label=proposed,teacher_version=shadow_policy['version'] if machine else version,label_source='machine',admitted_epoch=time.time())
  from corpus import preserve,machine_dataset
  preserve(root,pool.values(),root/'frames')
  # Preserve only a bounded set of native pseudo-label crops. Human backups are independent.
  newest=eligible_pseudo([],sorted(pool.values(),key=lambda r:r['admitted_epoch'],reverse=True))[:2000];pool={r['id']:r for r in newest}
  for p in (root/'frames').glob('*.png'):
   if p.stem not in pool:p.unlink()
  # Retain reviewed comparisons for longitudinal metrics; bound only pending rows.
  if len(pairs)>20000:
   pending=sorted(((k,v) for k,v in pairs.items() if v.get('truth') is None),key=lambda kv:kv[1]['captured_epoch'],reverse=True)[:20000]
   pairs={**{k:v for k,v in pairs.items() if v.get('truth') is not None},**dict(pending)}
  save(root/'pseudo-labels.json',pool);save(root/'comparisons.json',pairs);save(root/'metrics.json',dict(score([r for r in pairs.values() if r['human_version']==version and r['hybrid_version']==state['shadow_version']]),human_version=version,hybrid_version=state['shadow_version'],updated_epoch=time.time()))
  try:
   from comparison import publish as publish_comparison
   if not machine:publish_comparison(root,c['ssh_helper'])
   state.pop('comparison_sync_error',None)
  except Exception as exc:state['comparison_sync_error']=str(exc)
  state.update(pseudo_labels=len(pool),comparison_objects=len(pairs),updated_epoch=time.time(),phase='waiting_for_qualified_machine_frames' if not pool else 'collecting',reason='No machine labels yet pass confidence, consistency, and human-override checks; human model remains live.' if not pool else None)
  save(root/'status.json',state)
  if machine:
   folder,blockers=machine_dataset(root,code)
   if blockers:
    state.update(phase='collecting',reason='Machine-only training requires valid machine-labeled examples of both classes.',dataset_blockers=blockers);save(root/'status.json',state);return
   if time.time()-state.get('trained_epoch',0)<c.get('training_interval_seconds',86400):return
   if human_state.get('phase') in {'snapshot','building','training','evaluating','activating','activation_pending'}:return
   state.update(run_directory=str(folder),dataset_blockers=[],reason='Training machine-only model; shared human-reviewed evaluation follows.');save(root/'status.json',state)
   finish_training(root,folder,code,human_root,state);return
  if len(pool)<c.get('minimum_pseudo_labels',200) or time.time()-state.get('trained_epoch',0)<c.get('training_interval_seconds',86400):return
  if human_state.get('phase') in {'snapshot','building','training','evaluating','activating','activation_pending'}:return
  if not backup.exists():state.update(phase='waiting_for_verified_human_backup');save(root/'status.json',state);return
  from snapshot import export
  from dataset import build
  state.update(phase='snapshot',reason='Preparing the verified human training snapshot.');save(root/'status.json',state)
  with (backup/'backup-read.lock').open('a') as pin:
   fcntl.flock(pin,fcntl.LOCK_SH);snap=export(backup,root/'reviews')
  reviews=root/'reviews'/snap['fingerprint'];human_rows=read(reviews/'reviews.json')['samples'];pseudo=eligible_pseudo(human_rows,list(pool.values()))
  if len(pseudo)<c.get('minimum_pseudo_labels',200):
   state.update(phase='collecting',reason='Waiting for more unique machine labels after applying human overrides.',eligible_pseudo_labels=len(pseudo));save(root/'status.json',state);return
  key=hashlib.sha256(json.dumps([snap['fingerprint'],[(r['id'],r['pixel_sha256'],r['label']) for r in pseudo]],sort_keys=True).encode()).hexdigest();folder=root/'runs'/key
  if folder.exists() and not (folder/'candidate-policy.json').exists():folder.rename(folder.with_name(key+'.incomplete.'+str(time.time_ns())))
  if (folder/'candidate-policy.json').exists():
   state.update(phase='shadow_ready',shadow_folder=str(folder),shadow_version=key,shadow_seed_only=False,trained_epoch=time.time());save(root/'status.json',state);return
  state.update(phase='building',run_directory=str(folder));save(root/'status.json',state)
  built=build(human_root/'baseline/dataset-001',reviews,folder,root/'split-ledger.json')
  for row in pseudo:
   image='images/pseudo-'+row['id']+'.png';os.link(root/'frames'/(row['id']+'.png'),folder/image)
   built['samples'].append(dict(origin='pseudo:'+row['id'],label=row['label'],group='machine:'+row['generation'],pixel_sha256=row['pixel_sha256'],native_width=row['native_width'],native_height=row['native_height'],image=image,split='train',human_confirmed=False,pseudo_label=True,input_color_space='RGB'))
  from collections import Counter
  built['counts']=dict(Counter(r['label'] for r in built['samples']))
  built.update(training_lane='hybrid',fingerprint=key,training_strategy='recording_balanced',shadow_only=True,pseudo_labels=len(pseudo),human_baseline_version=version);save(folder/'dataset.json',built)
  finish_training(root,folder,code,human_root,state)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();config=read(a.config)
 try:run(config)
 except Exception as e:
  root=Path(config['root']);state=read(root/'status.json',{});state.update(phase='retry_pending',error=str(e),updated_epoch=time.time());save(root/'status.json',state);raise
