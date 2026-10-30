"""Reviewed email crops enter appearance training; no invented temporal ground truth."""
import hashlib,json
from pathlib import Path
from PIL import Image
LABELS={'anomalous','airplane','bird','insect','cloud','tree','other_animal','balloon','drone','unknown'}
def reviewed_examples(data):
 root=Path(data)/'email-reviews';result=[]
 for p in sorted((root/'examples').glob('*/review.json')):
  r=json.loads(p.read_text())
  if r.get('deleted') or r.get('label') not in LABELS or not r.get('human_confirmed'):continue
  image=p.parent/'native-object.png'
  if image.is_symlink() or hashlib.sha256(image.read_bytes()).hexdigest()!=r['native_crop_sha256']:raise ValueError('Email training crop integrity failure')
  with Image.open(image) as im:w,h=im.size
  result.append(dict(id=r.get('sample_id',r['event_id']),label=r['label'],image=image,group='generation:'+r['generation'],native_width=w,native_height=h,review=r))
 return result

def store_review(data,record,crop_bytes):
 import fcntl,time
 root=Path(data)/'email-reviews';root.mkdir(parents=True,exist_ok=True)
 def save(path,value):
  path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,allow_nan=False));temp.replace(path)
 with (root/'review.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  key=hashlib.sha256((record['source']+':'+record['message_id']).encode()).hexdigest();audit=root/'history'/(key+'.json')
  if audit.exists():return 'already_imported'
  import re
  sample_id=record.get('sample_id',record['event_id'])
  if not re.fullmatch('[a-f0-9]{32}',sample_id):raise ValueError('Invalid training example ID')
  target=root/'examples'/sample_id;target.mkdir(parents=True,exist_ok=True);p=target/'review.json';previous=json.loads(p.read_text()) if p.exists() else {}
  if record['reviewed_epoch']>=previous.get('reviewed_epoch',0):
   temp=target/'native-object.tmp';temp.write_bytes(crop_bytes);temp.replace(target/'native-object.png');save(p,record)
  save(audit,dict(record,previous=previous))
  examples=[json.loads(p.read_text()) for p in (root/'examples').glob('*/review.json')]
  save(root/'training-manifest.json',dict(updated_epoch=time.time(),examples=examples,classes=sorted({e['label'] for e in examples if e.get('multiclass_ready') and not e.get('deleted')})))
  return 'imported'
