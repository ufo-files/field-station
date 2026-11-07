"""Reviewed email crops enter appearance training; no invented temporal ground truth."""
import hashlib,json,io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image,ImageChops
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
  provenance='original'
  color_meta=p.parent/'color-review.json';color_image=p.parent/'color-native-object.png'
  if color_meta.is_file() and color_image.is_file() and not color_meta.is_symlink() and not color_image.is_symlink():
   color=json.loads(color_meta.read_text())
   if color.get('original_crop_sha256')==r['native_crop_sha256'] and color.get('event_id')==r['event_id'] and color.get('bounds')==r.get('bounds'):
    replacement=color_image.read_bytes()
    if hashlib.sha256(replacement).hexdigest()!=color['color_crop_sha256']:raise ValueError('Recovered color crop integrity failure')
    raw=replacement;image=color_image;provenance='verified_color_recovery'
  with Image.open(io.BytesIO(raw)) as source:
   w,h=source.size
   result=dict(id=r.get('sample_id',r['event_id']),label=r['label'],image=image,group='generation:'+r['generation'],native_width=w,native_height=h,review=r,color_provenance=provenance)
   if prepared:
    im=source.convert('RGB');bands=im.split();color=provenance=='verified_color_recovery' or r.get('source_color_space')=='RGB' or bool(ImageChops.difference(bands[0],bands[1]).getbbox() or ImageChops.difference(bands[1],bands[2]).getbbox());result['input_color_space']='RGB' if color else 'legacy_grayscale';out=io.BytesIO();im.save(out,format='PNG')
    result.update(normalized_png=out.getvalue(),pixel_sha256=hashlib.sha256(f'{w}x{h}:RGB:'.encode()+im.tobytes()).hexdigest())
  return result
 paths=sorted((root/'examples').glob('*/review.json'))
 if workers<=1:return [r for p in paths if (r:=load(p)) is not None]
 with ThreadPoolExecutor(max_workers=min(workers,4)) as pool:return [r for r in pool.map(load,paths) if r is not None]

# A request-local batch holds the existing review lock and publishes its index
# once. Per-object records and retry receipts remain authoritative.
import threading
from contextlib import contextmanager,nullcontext
_REVIEW_BATCH=threading.local()

def current_review_index(data):
 state=getattr(_REVIEW_BATCH,'state',None)
 return state['examples'] if state and state['root']==Path(data)/'email-reviews' else None

def batch_metadata_cache(data):
 state=getattr(_REVIEW_BATCH,'state',None)
 return state.setdefault('archive_metadata',{}) if state and state['root']==Path(data)/'email-reviews' else None

@contextmanager
def review_batch(data):
 import fcntl,time
 root=Path(data)/'email-reviews';root.mkdir(parents=True,exist_ok=True)
 if getattr(_REVIEW_BATCH,'state',None):raise RuntimeError('Nested review batch')
 with (root/'review.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);manifest=root/'training-manifest.json';examples=root/'examples';dirty=False
  try:
   if examples.stat().st_mtime_ns>manifest.stat().st_mtime_ns:raise ValueError('Stale index')
   rows=json.loads(manifest.read_text())['examples']
  except (OSError,KeyError,ValueError):
   from concurrent.futures import ThreadPoolExecutor
   paths=[p/'review.json' for p in examples.iterdir()] if examples.exists() else []
   with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(lambda p:json.loads(p.read_text()),paths))
   dirty=True
  state=dict(root=root,examples=rows,dirty=dirty);_REVIEW_BATCH.state=state
  try:yield
  finally:
   try:
    if state['dirty']:
     rows=state['examples'];value=dict(updated_epoch=time.time(),examples=rows,classes=sorted({e['label'] for e in rows if e.get('multiclass_ready') and not e.get('deleted')}))
     temp=manifest.with_suffix('.tmp');temp.write_text(json.dumps(value,allow_nan=False));temp.replace(manifest)
   finally:del _REVIEW_BATCH.state

def store_review(data,record,crop_bytes):
 import fcntl,time
 root=Path(data)/'email-reviews';root.mkdir(parents=True,exist_ok=True)
 def save(path,value):
  path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,allow_nan=False));temp.replace(path)
 state=getattr(_REVIEW_BATCH,'state',None)
 if state and state['root']!=root:raise ValueError('Review batch root mismatch')
 with nullcontext() if state else (root/'review.lock').open('a') as lock:
  if not state:fcntl.flock(lock,fcntl.LOCK_EX)
  key=hashlib.sha256((record['source']+':'+record['message_id']).encode()).hexdigest();audit=root/'history'/(key+'.json')
  if audit.exists():return 'already_imported'
  import re
  sample_id=record.get('sample_id',record['event_id'])
  if not re.fullmatch('[a-f0-9]{32}',sample_id):raise ValueError('Invalid training example ID')
  from object_omission import omitted
  object_id=record['event_id'] if sample_id==record['event_id'] else 'review:'+record['event_id']+':'+sample_id
  if omitted(data,object_id):raise ValueError('Object was deleted')
  manifest=root/'training-manifest.json';examples_root=root/'examples';indexed=None
  try:
   if not state and examples_root.stat().st_mtime_ns<=manifest.stat().st_mtime_ns:indexed=json.loads(manifest.read_text())['examples']
  except (OSError,KeyError,ValueError):pass
  if state:indexed=state['examples']
  target=root/'examples'/sample_id;target.mkdir(parents=True,exist_ok=True);p=target/'review.json';previous=json.loads(p.read_text()) if p.exists() else {}
  if record['reviewed_epoch']>=previous.get('reviewed_epoch',0):
   temp=target/'native-object.tmp';temp.write_bytes(crop_bytes);temp.replace(target/'native-object.png');save(p,record)
  save(audit,dict(record,previous=previous))
  if indexed is None:examples=[json.loads(p.read_text()) for p in (root/'examples').glob('*/review.json')]
  else:
   examples=[r for r in indexed if r.get('sample_id',r.get('event_id'))!=sample_id]
   examples.append(json.loads(p.read_text()))
  if state:state.update(examples=examples,dirty=True)
  else:save(root/'training-manifest.json',dict(updated_epoch=time.time(),examples=examples,classes=sorted({e['label'] for e in examples if e.get('multiclass_ready') and not e.get('deleted')})))
  return 'imported'
