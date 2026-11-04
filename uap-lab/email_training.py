"""Reviewed email crops enter appearance training; no invented temporal ground truth."""
import hashlib,json,io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image
from classification_taxonomy import LABELS,canonical_label

def reviewed_examples(data,workers=1,prepared=False):
 root=Path(data)/'email-reviews'
 def load(p):
  r=json.loads(p.read_text());r.setdefault('original_label',r.get('label'));r['label']=canonical_label(r.get('label'))
  if r.get('deleted') or r.get('label') not in LABELS or not r.get('human_confirmed'):return None
  image=p.parent/'native-object.png'
  if image.is_symlink():raise ValueError('Email training crop integrity failure')
  raw=image.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=r['native_crop_sha256']:raise ValueError('Email training crop integrity failure')
  with Image.open(io.BytesIO(raw)) as source:
   w,h=source.size
   result=dict(id=r.get('sample_id',r['event_id']),label=r['label'],image=image,group='generation:'+r['generation'],native_width=w,native_height=h,review=r)
   if prepared:
    im=source.convert('RGB');out=io.BytesIO();im.save(out,format='PNG')
    result.update(normalized_png=out.getvalue(),pixel_sha256=hashlib.sha256(f'{w}x{h}:RGB:'.encode()+im.tobytes()).hexdigest())
  return result
 paths=sorted((root/'examples').glob('*/review.json'))
 if workers<=1:return [r for p in paths if (r:=load(p)) is not None]
 with ThreadPoolExecutor(max_workers=min(workers,4)) as pool:return [r for r in pool.map(load,paths) if r is not None]

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
  manifest=root/'training-manifest.json';examples_root=root/'examples';indexed=None
  try:
   if examples_root.stat().st_mtime_ns<=manifest.stat().st_mtime_ns:indexed=json.loads(manifest.read_text())['examples']
  except (OSError,KeyError,ValueError):pass
  target=root/'examples'/sample_id;target.mkdir(parents=True,exist_ok=True);p=target/'review.json';previous=json.loads(p.read_text()) if p.exists() else {}
  if record['reviewed_epoch']>=previous.get('reviewed_epoch',0):
   temp=target/'native-object.tmp';temp.write_bytes(crop_bytes);temp.replace(target/'native-object.png');save(p,record)
  save(audit,dict(record,previous=previous))
  if indexed is None:examples=[json.loads(p.read_text()) for p in (root/'examples').glob('*/review.json')]
  else:
   examples=[r for r in indexed if r.get('sample_id',r.get('event_id'))!=sample_id]
   examples.append(json.loads(p.read_text()))
  save(root/'training-manifest.json',dict(updated_epoch=time.time(),examples=examples,classes=sorted({e['label'] for e in examples if e.get('multiclass_ready') and not e.get('deleted')})))
  return 'imported'
