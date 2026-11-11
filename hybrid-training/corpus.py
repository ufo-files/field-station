"""Preserved machine-label evidence, independent of the bounded collection cache."""
import hashlib,json,os,time,shutil
from pathlib import Path
from PIL import Image

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.replace(path)

def preserve(root,rows,frames):
 corpus=root/'corpus';images=corpus/'images';images.mkdir(parents=True,exist_ok=True)
 path=corpus/'manifest.json';existing=json.loads(path.read_text()) if path.exists() else {}
 for row in rows:
  if row.get('human_confirmed') or row.get('label_source','machine')!='machine':raise ValueError('Human label cannot enter machine-label corpus')
  source=frames/(row['id']+'.png')
  if not source.is_file():continue
  with Image.open(source) as im:
   im=im.convert('RGB');digest=hashlib.sha256(f'{im.width}x{im.height}:RGB:'.encode()+im.tobytes()).hexdigest()
  if digest!=row['pixel_sha256']:raise ValueError('Machine crop pixel checksum mismatch')
  key=hashlib.sha256(json.dumps([row['id'],digest,row['label'],row.get('teacher_version')]).encode()).hexdigest()
  target=images/(key+'.png')
  if not target.exists():shutil.copyfile(source,target)
  existing.setdefault(key,dict(row,image='images/'+key+'.png',label_source='machine',human_confirmed=False,preserved_epoch=time.time()))
 save(path,existing)
 return existing

def machine_dataset(root,code):
 import sys
 sys.path.insert(0,str(code/'uap-lab/recognition'))
 from candidate_dataset import group_rows,assign_splits
 from collections import Counter
 manifest=root/'corpus/manifest.json';source=json.loads(manifest.read_text()) if manifest.exists() else {};rows=[]
 for key,row in source.items():
  if row.get('human_confirmed') or row.get('label_source')!='machine':raise ValueError('Machine-only dataset contains human labels')
  rows.append(dict(origin='machine:'+key,label=row['label'],group=row['generation'],pixel_sha256=row['pixel_sha256'],native_width=row['native_width'],native_height=row['native_height'],source=str(root/'corpus'/row['image']),human_confirmed=False,label_source='machine',teacher_version=row.get('teacher_version'),input_color_space='RGB'))
 rows,quarantine=group_rows(rows);coverage,blockers=assign_splits(rows)
 if set(r['label'] for r in rows)!={'anomalous','not_anomalous'}:blockers.append('Both machine-labeled classes are required')
 key=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest();folder=root/'runs'/key
 if not (folder/'dataset.json').exists():
  (folder/'images').mkdir(parents=True,exist_ok=True);samples=[]
  for i,row in enumerate(rows):
   image='images/'+str(i)+'.png';target=folder/image
   if not target.exists():os.link(row['source'],target)
   samples.append(dict({k:v for k,v in row.items() if k!='source'},image=image))
  save(folder/'dataset.json',dict(fingerprint=key,classes=['anomalous','not_anomalous'],samples=samples,counts=dict(Counter(r['label'] for r in samples)),blockers=blockers,quarantine=quarantine,independent_groups=coverage,human_training_counts={},pseudo_labels=len(samples),training_strategy='recording_balanced',training_lane='machine_only',shadow_only=True,limitations=['Training and internal split labels are machine-generated; internal scores are agreement, not human-verified accuracy']))
 save(root/'dataset-current.json',dict(directory=str(folder),fingerprint=key,examples=len(rows),blockers=blockers,training_lane='machine_only'))
 return folder,blockers
