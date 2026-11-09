"""One object library; model suggestions never imply human approval."""
import base64,hashlib,json,os,re,threading,time,uuid
from pathlib import Path
from label_queue import read
from email_training import canonical_label,LABELS
from retired_data import ids as retired_ids,visible as retirement_visible
_CACHE={}
_LOCK=threading.RLock()
_SAVE_LOCK=threading.RLock()
_OVERRIDES={}
_BUILDING={}
_REVISION=0
_ERRORS={}
VIEWS={'all','anomalous','not_anomalous','needs_review','human_reviewed','human_reviewed_anomalous'}

def cache_path(data):
 runtime=os.environ.get('XDG_RUNTIME_DIR')
 if not runtime:return Path(data)/'object-library-cache.json'
 return Path(runtime)/'review-cache'/(hashlib.sha256(str(data).encode()).hexdigest()+'.json')


def invalidate():
 global _REVISION
 with _LOCK:_REVISION+=1;_CACHE.clear();_OVERRIDES.clear()

def reviewed(key,category):
 global _REVISION
 with _LOCK:
  _OVERRIDES[key]=category
  for name,(stamp,rows) in _CACHE.items():
   for row in rows:
    if row['id']==key:row.update(label=category,human_reviewed=True)

def refresh(data,wait=False):
 name=str(data)
 with _LOCK:
  if name not in _CACHE:
   saved=read(cache_path(data),{})
   # Persisted rows are complete but stale; zero is reserved for partial builds.
   if saved.get('schema')==1:_CACHE[name]=(-1,saved['items'])
  if name not in _BUILDING and (name not in _CACHE or time.monotonic()-_CACHE[name][0]>60):
   done=threading.Event();_BUILDING[name]=done;revision=_REVISION;had_cache=name in _CACHE
   def build():
    try:
     def publish(rows):
      with _LOCK:
       if revision!=_REVISION or had_cache:return
       for row in rows:
        if row['id'] in _OVERRIDES:row.update(label=_OVERRIDES[row['id']],human_reviewed=True)
       _CACHE[name]=(0,rows)
     rows=collect(data,publish)
     with _LOCK:
      if revision==_REVISION:
       for row in rows:
        if row['id'] in _OVERRIDES:row.update(label=_OVERRIDES[row['id']],human_reviewed=True)
       _CACHE[name]=(time.monotonic(),rows);_ERRORS.pop(name,None)
     # This cache is advisory: listing overlays current labels and clear cutoffs.
     # Disk persistence must never hold the lock serving interactive requests.
     target=cache_path(data);target.parent.mkdir(parents=True,exist_ok=True)
     temp=target.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(dict(schema=1,items=rows)));temp.replace(target)
    except Exception as exc:
     with _LOCK:_ERRORS[name]=str(exc)
    finally:
     with _LOCK:_BUILDING.pop(name,None);done.set()
   threading.Thread(target=build,daemon=True).start()
  done=_BUILDING.get(name)
 if wait and done:done.wait(60)
 with _LOCK:return _CACHE.get(name),name in _BUILDING,_ERRORS.get(name)


def collect(data,publish=None):
 import labeled_frames
 rows={};root=data.parent/'notifications/outbox';retired_samples,retired_events=retired_ids(data)
 # Start from the atomic review manifest; publish useful views before historical video scans.
 for r in read(data/'email-reviews/training-manifest.json',{}).get('examples',[]):
  label=canonical_label(r.get('label'))
  if r.get('deleted') or not r.get('human_confirmed') or label not in LABELS:continue
  event=r.get('event_id','');sample=r.get('sample_id',event)
  if not re.fullmatch('[a-f0-9]{32}',event) or not re.fullmatch('[a-f0-9]{32}',sample):continue
  key=event if sample==event else f'review:{event}:{sample}';image='/api/labeled-image?source=review&id='+event+'&annotation='+sample
  rows[key]=dict(id=key,kind='review',video_id=event,sample_id=sample,created=r.get('reviewed_epoch',0),label=label,human_reviewed=True,image_url=image,frame_url=image,review_url='/email-review?id='+event,model_label=r.get('model_label'))
 from queue_index import ordered
 cleared_before=read(data/'review-queue-cleared.json',{}).get('cutoff_epoch',float('-inf'));added=0
 from recognition.recognition_alerts import recent_detections
 arrivals,complete=recent_detections(root,cleared_before)
 if complete:
  for row in arrivals:
   if row['id'] in rows:rows[row['id']]['model_label']=row.get('model_label')
   else:rows[row['id']]=row
 # The durable arrivals index covers everything since the last clear.
 for _,key in ([] if complete else ordered(root)):
  # The manifest already supplies reviewed rows; do not reopen their archived events.
  if key in retired_events or key in rows:continue
  folder=root/key
  path=folder/'event.json';key=folder.name
  if not re.fullmatch('[a-f0-9]{32}',key) or key in retired_events:continue
  e=read(path,{})
  if e.get('created_epoch',0)<=cleared_before:continue
  model_label=canonical_label(e.get('classification'))
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
  if reviewed:continue
  added+=1
  if publish and added%25==0:publish(sorted(rows.values(),key=lambda r:(r['created'],r['id']),reverse=True))
 if publish:publish(sorted(rows.values(),key=lambda r:(r['created'],r['id']),reverse=True))
 for row in labeled_frames.listing(all_items=True,include_reviews=False)['items']:
  kind=row['kind'];a=row['annotation'];key=f"{kind}:{row['video_id']}:{a['id']}"
  if kind=='review' and a['id']==row['video_id']:key=row['video_id']
  rows[key]=dict(id=key,kind=kind,video_id=row['video_id'],sample_id=a['id'],created=row['created'],label=a['label'],human_reviewed=row.get('human_reviewed',True),image_url=row['image_url'],frame_url=row['image_url'],review_url=row.get('review_url') or ('/?view=label&video='+row['video_id'] if kind=='video' else None),model_label=rows.get(key,{}).get('model_label'))
  if kind=='video' and row['original_available']:rows[key].update(frame_url='/api/frame?id='+row['video_id']+'&time='+str(a['time']),frame_bounds=a.get('bounds'))
 return sorted(rows.values(),key=lambda r:(r['created'],r['id']),reverse=True)

def current_reviews(rows,records):
 """Saved human reviews override stale index rows and replace original proposals."""
 reviews={};events=set()
 for r in records:
  label=canonical_label(r.get('label'));event=r.get('event_id','');sample=r.get('sample_id') or event
  if r.get('deleted') or not r.get('human_confirmed') or label not in LABELS:continue
  if not re.fullmatch('[a-f0-9]{32}',event) or not re.fullmatch('[a-f0-9]{32}',sample):continue
  key=event if sample==event else f'review:{event}:{sample}';image='/api/labeled-image?source=review&id='+event+'&annotation='+sample
  reviews[key]=dict(id=key,kind='review',video_id=event,sample_id=sample,created=r.get('reviewed_epoch',0),label=label,human_reviewed=True,image_url=image,frame_url=image,review_url='/email-review?id='+event,model_label=r.get('model_label'));events.add(event)
 result=[]
 for row in rows:
  if row['kind']=='review' or (row['kind']=='detection' and row['id'] in events):
   if row['id'] in reviews:reviews[row['id']]['model_label']=row.get('model_label')
   continue
  result.append(row)
 result.extend(reviews.values())
 return sorted(result,key=lambda row:(row['created'],row['id']),reverse=True)

def listing(data,view='all',before='',limit=100,wait=False,classification=None,review_status=None):
 if view=='manual_recordings':
  from manual_recordings import listing as manual_listing
  result=manual_listing(data,Path(os.environ.get("CAPTURE_STATION_ROOT",str(Path(__file__).resolve().parent.parent/"capture-station"))),before,limit)
  detection_counts=listing(data,'all',limit=1).get('source_counts',{})
  result['source_counts']=dict(detection_counts,manual_recordings=result['total'])
  return result
 if view not in VIEWS:raise ValueError('Invalid object view')
 limit=max(1,min(100,int(limit)));data=Path(data)
 cached,indexing,error=refresh(data,wait)
 records=read(data/'email-reviews/training-manifest.json',{}).get('examples',[])
 retired_samples,retired_events=retired_ids(data,records)
 cleared_before=read(data/'review-queue-cleared.json',{}).get('cutoff_epoch',float('-inf'))
 from recognition.recognition_alerts import recent_detections
 arrivals,arrivals_complete=recent_detections(data.parent/'notifications/outbox',cleared_before)
 merged={r['id']:r for r in (cached[1] if cached else [])};merged.update({r['id']:r for r in arrivals})
 rows=current_reviews(list(merged.values()),records)
 omitted=read(data/'omitted-objects.json',{}).get('objects',{})
 rows=[row for row in rows if row['id'] not in omitted]
 rows=[row for row in rows if retirement_visible(row,retired_samples,retired_events) and (row['human_reviewed'] or row.get('created',0)>cleared_before)]
 # Cached suggestions must not outlive their source directory. Human reviews
 # remain backed by their separately preserved training crops.
 if any(row['kind']=='detection' for row in rows):
  try:present=set(os.listdir(Path(data).parent/'notifications/outbox'))
  except FileNotFoundError:present=set()
  rows=[row for row in rows if row['kind']!='detection' or row['id'] in present]
 counts={v:0 for v in VIEWS}
 def matches(row,v):
  if v=='human_reviewed_anomalous':return row['human_reviewed'] and row['label']=='anomalous'
  return v=='all' or (row['human_reviewed'] if v=='human_reviewed' else (not row['human_reviewed'] and row['label']=='anomalous') if v=='needs_review' else row['label']==v)
 for row in rows:
  for v in VIEWS:counts[v]+=matches(row,v)
 filtered=[r for r in rows if matches(r,view)];filter_counts=None
 if classification is not None or review_status is not None:
  from review_filters import select
  filtered,filter_counts=select(filtered,classification or 'all',review_status or 'all')
 filtered_total=len(filtered)
 if before:
  try:stamp,key=json.loads(base64.urlsafe_b64decode(before.encode()));filtered=[r for r in filtered if (r['created'],r['id'])<(stamp,key)]
  except Exception:raise ValueError('Invalid object cursor')
 from archive_links import attach
 page=attach(data,[dict(r) for r in filtered[:limit]]);cursor=None
 if len(filtered)>limit:cursor=base64.urlsafe_b64encode(json.dumps([page[-1]['created'],page[-1]['id']]).encode()).decode()
 from manual_recordings import listing as manual_listing
 source_counts={'manual_recordings':manual_listing(data,Path(os.environ.get("CAPTURE_STATION_ROOT",str(Path(__file__).resolve().parent.parent/"capture-station"))),limit=1)['total']}
 if cached is not None and cached[0]!=0:source_counts['detections']=counts['all']
 return dict(items=page,total=filtered_total,source_counts=source_counts,counts=counts,filter_counts=filter_counts,counts_indexing=cached is None or cached[0]==0,indexing=indexing and not ((view=='needs_review' or review_status=='needs_review') and arrivals_complete),ready=cached is not None or arrivals_complete,index_error=error,next_cursor=cursor,labels=sorted(LABELS))

def label(data,body):
 """Idempotent human corrections use original crops and retain review history."""
 import label_queue,labeled_frames
 from email_training import store_review
 from review_archive import invalidate_event,record_decision
 data=Path(data);key=body.get('id','');category=canonical_label(body.get('label'));request=body.get('request_id','')
 if category not in LABELS or not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('Invalid label request')
 with _SAVE_LOCK:
  from object_omission import omitted
  if omitted(data,key):raise ValueError('Object was deleted')
  if re.fullmatch('[a-f0-9]{32}',key):
   audit=hashlib.sha256(('station_web_review:quick-label:'+request).encode()).hexdigest()
   receipt=read(data/'email-reviews/history'/(audit+'.json'),{})
   if receipt:
    if receipt.get('event_id')!=key or canonical_label(receipt.get('label'))!=category:raise ValueError('Request already used')
    return dict(saved=True,id=key,label=category)
   existing=read(data/'email-reviews/examples'/key/'review.json',{})
   if not existing.get('human_confirmed') or existing.get('deleted'):
    result=label_queue.label(data,dict(body,allow_update=True));reviewed(key,category);return result
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
  reviewed(key,category);return dict(saved=True,id=key,label=category,human_reviewed=True)


def label_batch(data,body):
 from email_training import review_batch
 items=body.get('items')
 if not isinstance(items,list) or not 1<=len(items)<=50 or any(not isinstance(i,dict) for i in items):raise ValueError('Choose between 1 and 50 objects')
 results=[]
 reset_before=read(Path(data)/'review-pending-reset.json',{}).get('epoch',0)
 with _SAVE_LOCK,review_batch(data):
  for item in items:
   if reset_before and (not isinstance(item.get('queued_at'),(int,float)) or item['queued_at']<=reset_before):
    results.append(dict(saved=False,discarded=True,id=item.get('id'),request_id=item.get('request_id'),error='Pending label discarded at your request'));continue
   from object_omission import omitted
   if omitted(data,item.get('id')):
    results.append(dict(saved=False,discarded=True,id=item.get('id'),request_id=item.get('request_id'),error='Object was deleted'));continue
   try:results.append(dict(label(data,item),request_id=item.get('request_id')))
   except (ValueError,OSError,KeyError,TypeError) as exc:results.append(dict(saved=False,id=item.get('id') if isinstance(item,dict) else None,request_id=item.get('request_id') if isinstance(item,dict) else None,error=str(exc)))
 return dict(results=results)
