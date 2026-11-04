"""One object library; model suggestions never imply human approval."""
import base64,hashlib,json,re,threading,time,uuid
from pathlib import Path
from label_queue import read
from email_training import canonical_label,LABELS
_CACHE={}
_LOCK=threading.RLock()
VIEWS={'all','anomalous','not_anomalous','needs_review','human_reviewed'}

def invalidate():
 with _LOCK:_CACHE.clear()

def collect(data):
 import labeled_frames
 rows={};root=data.parent/'notifications/outbox'
 for row in labeled_frames.listing(all_items=True)['items']:
  kind=row['kind'];a=row['annotation'];key=f"{kind}:{row['video_id']}:{a['id']}"
  if kind=='review' and a['id']==row['video_id']:key=row['video_id']
  rows[key]=dict(id=key,kind=kind,video_id=row['video_id'],sample_id=a['id'],created=row['created'],label=a['label'],human_reviewed=row.get('human_reviewed',True),image_url=row['image_url'],frame_url=row['image_url'],review_url=row.get('review_url') or ('/?view=label&video='+row['video_id'] if kind=='video' else None),model_label=None)
  if kind=='video' and row['original_available']:rows[key]['frame_url']='/api/frame?id='+row['video_id']+'&time='+str(a['time'])
 for path in root.glob('*/event.json'):
  key=path.parent.name
  if not re.fullmatch('[a-f0-9]{32}',key):continue
  e=read(path,{});model_label=canonical_label(e.get('classification'))
  if model_label not in LABELS:continue # Never invent a label for a failed/legacy inference.
  reviewed=key in rows
  if not reviewed:
   if read(path.parent/'label-queue-dismissed.json',{}).get('dismissed'):continue
   delivery=read(path.parent/'delivery.json',{}).get('state')
   if delivery in ('cancelled','expired') or (delivery=='suppressed' and not e.get('review_only')):continue
   name=e.get('native_crop','native-object.png')
   if name not in ('native-object.png','object.png') or not (path.parent/name).is_file():continue
   rows[key]=dict(id=key,kind='detection',created=e.get('created_epoch',0),label=model_label,human_reviewed=False,image_url='/api/label-queue/image?id='+key,frame_url='/api/label-queue/image?full=1&id='+key,review_url='/email-review?id='+key)
  rows[key]['model_label']=model_label
  if (path.parent/'object.png').is_file():rows[key]['frame_url']='/api/label-queue/image?full=1&id='+key
 return sorted(rows.values(),key=lambda r:(r['created'],r['id']),reverse=True)

def listing(data,view='all',before='',limit=100):
 if view not in VIEWS:raise ValueError('Invalid object view')
 limit=max(1,min(100,int(limit)));data=Path(data)
 with _LOCK:
  cached=_CACHE.get(str(data))
  if cached is None or time.monotonic()-cached[0]>15:
   cached=(time.monotonic(),collect(data));_CACHE[str(data)]=cached
  rows=cached[1]
 counts={v:0 for v in VIEWS}
 def matches(row,v):return v=='all' or (row['human_reviewed'] if v=='human_reviewed' else not row['human_reviewed'] if v=='needs_review' else row['label']==v)
 for row in rows:
  for v in VIEWS:counts[v]+=matches(row,v)
 filtered=[r for r in rows if matches(r,view)]
 if before:
  try:stamp,key=json.loads(base64.urlsafe_b64decode(before.encode()));filtered=[r for r in filtered if (r['created'],r['id'])<(stamp,key)]
  except Exception:raise ValueError('Invalid object cursor')
 page=filtered[:limit];cursor=None
 if len(filtered)>limit:cursor=base64.urlsafe_b64encode(json.dumps([page[-1]['created'],page[-1]['id']]).encode()).decode()
 return dict(items=page,total=counts[view],counts=counts,next_cursor=cursor,labels=sorted(LABELS))

def label(data,body):
 """Idempotent human corrections use original crops and retain review history."""
 import label_queue,labeled_frames
 from email_training import store_review
 from review_archive import invalidate_event,record_decision
 data=Path(data);key=body.get('id','');category=canonical_label(body.get('label'));request=body.get('request_id','')
 if category not in LABELS or not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('Invalid label request')
 with _LOCK:
  if re.fullmatch('[a-f0-9]{32}',key):
   audit=hashlib.sha256(('station_web_review:quick-label:'+request).encode()).hexdigest()
   receipt=read(data/'email-reviews/history'/(audit+'.json'),{})
   if receipt:
    if receipt.get('event_id')!=key or canonical_label(receipt.get('label'))!=category:raise ValueError('Request already used')
    return dict(saved=True,id=key,label=category)
   existing=read(data/'email-reviews/examples'/key/'review.json',{})
   if not existing.get('human_confirmed') or existing.get('deleted'):
    result=label_queue.label(data,dict(body,allow_update=True));invalidate();return result
   parts=['review',key,key]
  else:parts=key.split(':')
  if len(parts)!=3 or parts[0] not in ('review','video','preserved') or any(not re.fullmatch('[a-f0-9]{32}',v) for v in parts[1:]):raise ValueError('Invalid object')
  kind,vid,aid=parts
  if kind=='review':
   p=data/'email-reviews/examples'/aid;record=read(p/'review.json',{})
   if record.get('event_id')!=vid or record.get('deleted'):raise ValueError('Review no longer exists')
   crop=(p/'native-object.png').read_bytes()
   if hashlib.sha256(crop).hexdigest()!=record.get('native_crop_sha256'):raise ValueError('Crop checksum does not match')
   invalidate_event(data,vid)
   store_review(data,dict(record,label=category,human_confirmed=True,binary_anomalous=category=='anomalous',multiclass_ready=True,reviewed_epoch=time.time(),source='station_web_review',message_id='object-label:'+request),crop)
   label_queue.complete_anomalous_detection(data,vid,category)
  else:
   import lab
   # Preserved annotations get a local authoritative copy, with crops retained on SSD.
   import shutil
   folder=data/'videos'/vid
   if kind=='preserved' and not (folder/'video.json').exists():
    source=labeled_frames.preserved_root()/'videos'/vid;folder.mkdir(parents=True,exist_ok=True)
    annotations=read(source/'annotations.json',[])
    for a in annotations:
     src=source/a['image'];dest=folder/a['image']
     if src.is_symlink() or src.resolve().parent!=source.resolve() or dest.parent!=folder:raise ValueError('Invalid preserved crop')
     shutil.copy2(src,dest)
    for name in ('annotations.json','review.json','training-excluded.json'):
     if (source/name).exists():shutil.copy2(source/name,folder/name)
    lab.save(folder/'video.json',read(source/'video.json',{}))
   with lab._per_video_lock(lab._REVIEW_LOCKS,folder):
    annotations=read(folder/'annotations.json',[]);a=next((a for a in annotations if a['id']==aid),None)
    if not a:raise ValueError('Object no longer exists')
    history=folder/'annotation-history';history.mkdir(exist_ok=True);receipt=history/('label-'+request+'.json')
    if not read(receipt,{}).get('saved'):
     lab.save(receipt,dict(action='relabel',before=dict(a),label=category,epoch=time.time(),saved=False))
     a.update(label=category,human_confirmed=True,reviewed_epoch=time.time())
     lab.save(folder/'annotations.json',annotations)
     lab.save(receipt,dict(read(receipt,{}),saved=True))
     prior=read(folder/'review.json',{})
     if prior.get('completed') and not prior.get('automated_event'):
      prior['reviewed_at']=time.time();lab.save(folder/'review.json',prior);record_decision(folder,read(folder/'video.json',{}),prior)
  invalidate();return dict(saved=True,id=key,label=category,human_reviewed=True)
