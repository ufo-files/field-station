"""Fast human labeling of saved detection crops; never auto-completes a session."""
import hashlib,json,re,time,os
from pathlib import Path
from email_training import LABELS,store_review,canonical_label

def read(path,default=None):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return default

def folder(data,key):
 if not re.fullmatch('[a-f0-9]{32}',str(key)):raise ValueError('Invalid detection')
 root=Path(data).parent/'notifications/outbox';target=root/key
 if target.is_symlink() or not (target/'event.json').is_file():raise ValueError('Detection is no longer available')
 return target

def image_path(data,key,full=False):
 target=folder(data,key);event=read(target/'event.json',{})
 names=['object.png','source-frame.png'] if full else ['object-detail.png',event.get('native_crop','native-object.png')]
 for name in names:
  path=target/name
  if path.is_file() and not path.is_symlink() and path.resolve().parent==target.resolve():return path
 raise ValueError('Detection image unavailable')

def detections(data,before='',limit=100,include_obsolete=False):
 data=Path(data);limit=max(1,min(100,int(limit)));reviewed=set()
 manifest=data/'email-reviews/training-manifest.json';examples=data/'email-reviews/examples'
 try:
  if examples.stat().st_mtime_ns>manifest.stat().st_mtime_ns:raise ValueError('Index is stale')
  reviews=read(manifest,{})['examples']
 except (OSError,ValueError,KeyError):reviews=[read(p,{}) for p in examples.glob('*/review.json')]
 for r in reviews:
  if r.get('human_confirmed') and not r.get('deleted'):reviewed.add(r.get('event_id'))
 boundary=None
 if before:
  value=before.removeprefix('d:')
  if '~' in value:
   stamp,key=value.split('~',1)
   if not stamp.isdigit() or not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid cursor')
   boundary=(int(stamp),key)
  elif re.fullmatch('[a-f0-9]{32}',value):
   # Older open tabs used ID-only cursors; restart chronological paging.
   boundary=None
  else:raise ValueError('Invalid cursor')
 root=data.parent/'notifications/outbox'
 release=read(root.parent/'active-model-release.json',{})
 cleared_before=read(data/'review-queue-cleared.json',{}).get('cutoff_epoch',float('-inf'))
 from queue_index import ordered
 entries=ordered(root,boundary)
 keys=[key for stamp,key in entries];stamps=dict((key,stamp) for stamp,key in entries)
 rows=[];scanned=0;last=None
 for key in keys:
  path=root/key/'event.json';scanned+=1;last=key
  if key not in reviewed and not read(path.parent/'label-queue-dismissed.json',{}).get('dismissed') and read(path.parent/'delivery.json',{}).get('state') not in ('cancelled','expired') and (read(path.parent/'delivery.json',{}).get('state')!='suppressed' or read(path,{}).get('review_only')):
   e=read(path,{})
   obsolete=release.get('state')=='deployed' and release.get('health_verified') and e.get('model')!=release.get('version') and e.get('created_epoch',float('inf'))<=release['deployed_epoch'] and (release.get('clear_candidate_backlog') or time.time()-e.get('created_epoch',time.time())>=48*3600)
   name=e.get('native_crop','native-object.png')
   if (include_obsolete or not obsolete) and e.get('created_epoch',0)>cleared_before and name in ('native-object.png','object.png') and (path.parent/name).is_file():
    rows.append(dict(kind='detection',id=key,created=float(e.get('created_epoch',0)),suggested_label=e.get('classification','unknown'),image_url='/api/label-queue/image?id='+key,frame_url='/api/label-queue/image?full=1&id='+key,review_url='/email-review?id='+key))
  if len(rows)>=limit or scanned>=500:break
 more=scanned<len(keys);cursor=str(stamps[last])+'~'+last if last and more else None
 return dict(items=rows,total=len(rows) if not before and not more else None,next_cursor=cursor,labels=sorted(LABELS))

def lease_videos(data,keys):
 """Keep actively displayed review sources local; idle tabs expire naturally."""
 if not keys:return
 import fcntl,uuid
 data=Path(data);now=time.time();path=data/'review-leases.json'
 with (data/'review-leases.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  previous=read(path,{})
  leases={k:v for k,v in previous.items() if isinstance(v,(float,int)) and v>now}
  for key in keys:
   if leases.get(key,0)<now+600:leases[key]=now+900
  if leases!=previous:
   temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(leases));temp.replace(path)

def videos(data,before='',limit=100):
 data=Path(data);root=data/'videos';items=[]
 if before and not re.fullmatch('[a-f0-9]{32}',before):raise ValueError('Invalid cursor')
 omitted=read(data/'omitted-videos.json',{});reviewed=read(data/'reviewed-videos.json',{})
 try:
  with os.scandir(root) as entries:keys=sorted([e.name for e in entries if re.fullmatch('[a-f0-9]{32}',e.name) and (not before or e.name<before)],reverse=True)
 except FileNotFoundError:keys=[]
 scanned=0;last=None
 for key in keys:
  scanned+=1;last=key;target=root/key;m=read(target/'video.json',{});sha=m.get('sha256')
  quick=read(target/'quick-frame-review.json',{})
  frame_labeled=any(a.get('id')==quick.get('annotation_id') for a in read(target/'annotations.json',[])) if quick.get('annotation_id') else False
  if not frame_labeled and m and not m.get('media_expired') and sha not in omitted and not reviewed.get(sha,{}).get('completed') and not read(target/'training-excluded.json',{}).get('excluded') and not read(target/'review.json',{}).get('completed') and (target/'source').is_file():
   items.append(dict(kind='video',id=key,title=m.get('name','Recorded video'),image_url='/api/label-queue/video-image?id='+key,review_url='/?view=label&video='+key))
  if len(items)>=limit or scanned>=500:break
 lease_videos(data,[item['id'] for item in items])
 return dict(items=items,next_cursor=last if scanned<len(keys) else None,total=len(items) if not before and scanned==len(keys) else None)

def listing(data,before='',limit=100,source='detections'):
 limit=max(1,min(100,int(limit)))
 if source not in ('all','detections','videos'):raise ValueError('Invalid queue')
 # Legacy URLs also resolve to real detections; full recordings are reviewed separately.
 if before.startswith('v:'):before=''
 result=detections(data,before.removeprefix('d:'),limit)
 if result['next_cursor']:result['next_cursor']='d:'+result['next_cursor']
 result['labels']=sorted(LABELS)
 return result

def video_image(key):
 import lab,io,uuid
 from PIL import Image
 target=lab.video_path(key);meta=lab.read(target/'video.json',{})
 if not meta or not (target/'source').is_file():raise ValueError('Original video unavailable')
 cache=lab.DATA/'queue-thumbnails';cache.mkdir(exist_ok=True);path=cache/(key+'.jpg')
 if not path.exists():
  _,raw=lab.frame_at(target,0)
  with Image.open(io.BytesIO(raw)) as im:
   im.thumbnail((640,640));temp=cache/(key+'-'+uuid.uuid4().hex+'.tmp');im.convert('RGB').save(temp,format='JPEG',quality=85);temp.replace(path)
 return path

def complete_anomalous_detection(data,key,category):
 if category!='anomalous':return
 from email_review import annotation_revision,finish_review
 target=folder(data,key);previous=read(target/'review-completion.json',{})
 if previous.get('completed') and previous.get('annotation_revision')==annotation_revision(data,key):return
 finish_review(data,dict(id=key,completed=True))

def label(data,body):
 if body.get('kind')=='video':raise ValueError('Label a detected object; whole-video frame cards have been retired')
 data=Path(data);key=body['id'];target=folder(data,key);category=canonical_label(body.get('label'));request=body.get('request_id','')
 if category not in LABELS:raise ValueError('Choose a valid category')
 if not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('Invalid request ID')
 message='quick-label:'+request
 existing=read(data/'email-reviews/examples'/key/'review.json',{})
 if existing.get('message_id')==message and existing.get('label')==category:
  complete_anomalous_detection(data,key,category)
  return dict(saved=True,id=key,label=category)
 from email_review import event_reviews
 for r in event_reviews(data,key):
  if not body.get('allow_update') and r.get('event_id')==key and r.get('human_confirmed') and not r.get('deleted'):raise ValueError('This detection has already been reviewed. Open its video to change the label.')
 e=read(target/'event.json',{});path=target/e.get('native_crop','native-object.png')
 if path.is_symlink() or path.resolve().parent!=target.resolve():raise ValueError('Invalid crop')
 crop=path.read_bytes();digest=hashlib.sha256(crop).hexdigest()
 if digest!=e.get('native_crop_sha256'):raise ValueError('Original crop checksum does not match')
 record=dict(schema=1,event_id=key,sample_id=key,message_id=message,reviewed_epoch=time.time(),label=category,human_confirmed=True,source='station_web_review',generation=e['generation'],sequence=e.get('sequence'),pts_seconds=e['pts_seconds'],bounds=e['bounds'],model=e['model'],native_crop_sha256=digest,binary_anomalous=category=='anomalous',multiclass_ready=True,reviewer='station_web_ui')
 clip=read(target/'review-clip.json',{})
 if 'event_time' in clip:record['review_clip_time']=clip['event_time']
 from review_archive import invalidate_event
 invalidate_event(data,key);store_review(data,record,crop)
 complete_anomalous_detection(data,key,category)
 return dict(saved=True,id=key,label=category)


def clear_backlog(data,cutoff=None):
 import fcntl
 data=Path(data);reviews=data/'email-reviews';reviews.mkdir(parents=True,exist_ok=True)
 with (reviews/'review.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  return _clear_backlog(data,cutoff)

def _clear_backlog(data,cutoff=None):
 """Clear both pending queues without inventing reviews or deleting evidence."""
 import uuid
 data=Path(data);cutoff=time.time() if cutoff is None else float(cutoff);audit=data/'queue-clear-history'/uuid.uuid4().hex
 audit.mkdir(parents=True)
 def save(path,value):
  temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
  temporary.write_text(json.dumps(value));temporary.replace(path)
 def reviewed_events():
  return {r.get('event_id') for p in (data/'email-reviews/examples').glob('*/review.json') if (r:=read(p,{})).get('human_confirmed') and not r.get('deleted')}
 reviewed=reviewed_events();videos_cleared=[];frames_cleared=[];protected=[]
 candidates=[]
 for kind in ('videos','detections'):
  cursor=''
  while True:
   page=videos(data,before=cursor,limit=100) if kind=='videos' else detections(data,before=cursor,limit=100,include_obsolete=True);candidates.extend(page['items'])
   cursor=page.get('next_cursor')
   if not cursor:break
 with (audit/'actions.jsonl').open('a') as log:
  for row in candidates:
   key=row['id']
   if row['kind']=='video':
    target=data/'videos'/key;meta=read(target/'video.json',{});review=read(target/'review.json',{})
    if meta.get('created',0)>cutoff:continue
    if read(target/'annotations.json',[]) or review.get('completed') or review.get('reviewed_at'):
     protected.append(key);continue
    path=target/'training-excluded.json';value=dict(excluded=True,omitted_at=cutoff,reason='User cleared labeling backlog',queue_clear_id=audit.name)
   else:
    target=folder(data,key);event=read(target/'event.json',{})
    if event.get('created_epoch',0)>cutoff:continue
    if key in reviewed:protected.append(key);continue
    # Preserve delivery receipts; dismissing a label task is not a mail action.
    path=target/'label-queue-dismissed.json';value=dict(dismissed=True,epoch=cutoff,reason='User cleared labeling backlog',queue_clear_id=audit.name)
   log.write(json.dumps(dict(kind=row['kind'],id=key,path=str(path),previous=read(path,None)))+'\n');log.flush();os.fsync(log.fileno())
   save(path,value)
   (videos_cleared if row['kind']=='video' else frames_cleared).append(key)
 result=dict(videos_cleared=len(videos_cleared),frames_cleared=len(frames_cleared),protected=len(protected),cutoff_epoch=cutoff,audit=str(audit),media_deleted=False)
 save(audit/'result.json',result)
 # Shared by both queue APIs, including already-cached and late-indexed rows.
 prior=read(data/'review-queue-cleared.json',{}).get('cutoff_epoch',float('-inf'))
 if cutoff>=prior:save(data/'review-queue-cleared.json',dict(cutoff_epoch=cutoff,audit=str(audit)))
 return result


def label_video_frame(data,body):
 """Save the frame shown by video_image(), without claiming whole-clip review."""
 import lab
 key=lab.checked_id(body['id']);category=canonical_label(body.get('label'));request=body.get('request_id','')
 if category not in LABELS:raise ValueError('Choose a valid category')
 if not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('Invalid request ID')
 if Path(data).resolve()!=lab.DATA.resolve():raise ValueError('Invalid training data root')
 target=lab.video_path(key);aid=hashlib.sha256(('quick-video-frame:'+key+':'+request).encode()).hexdigest()[:32]
 with lab._per_video_lock(lab._REVIEW_LOCKS,target):
  meta=read(target/'video.json',{})
  if not meta or meta.get('media_expired'):raise ValueError('Video is unavailable')
  if read(target/'training-excluded.json',{}).get('excluded') or meta.get('sha256') in read(Path(data)/'omitted-videos.json',{}):raise ValueError('Video is excluded from training')
  existing=read(target/'annotations.json',[])
  previous=next((a for a in existing if a['id']==aid),None)
  if previous and previous['label']!=category:raise ValueError('Request already saved with a different label')
  # The queue thumbnail is frame zero, shown in full at reduced display size.
  # Save its native pixels through the same annotation path as manual review.
  if not previous:lab.annotate(key,0,dict(x=0,y=0,w=1,h=1),category,annotation_id=aid)
  lab.save(target/'quick-frame-review.json',dict(annotation_id=aid,label=category,request_id=request,reviewed_epoch=time.time(),scope='displayed_frame',time=0))
 return dict(saved=True,id=key,label=category,annotation_id=aid,kind='video',scope='displayed_frame')


def review_status(data, items):
 """Reconcile displayed cards against authoritative saved review records."""
 if not isinstance(items,list) or len(items)>500:raise ValueError('Choose at most 500 queue items')
 for item in items:
  if not isinstance(item,dict) or item.get('kind') not in ('video','detection') or not re.fullmatch('[a-f0-9]{32}',str(item.get('id',''))):raise ValueError('Invalid queue item')
 data=Path(data);lease_videos(data,[item['id'] for item in items if item['kind']=='video']);examples=data/'email-reviews/examples';manifest=data/'email-reviews/training-manifest.json'
 try:
  index=read(manifest,{})['examples']
  if examples.stat().st_mtime_ns>manifest.stat().st_mtime_ns:raise ValueError('Stale index')
 except (OSError,ValueError,KeyError):index=[read(p,{}) for p in examples.glob('*/review.json')]
 requested={item['id'] for item in items if item['kind']=='detection'};reviewed=set();saved_labels={}
 for record in index:
  if record.get('event_id') not in requested:continue
  sample=record.get('sample_id',record.get('event_id',''))
  if not re.fullmatch('[a-f0-9]{32}',str(sample)):continue
  current=read(examples/sample/'review.json',{})
  if current.get('human_confirmed') and not current.get('deleted'):
   reviewed.add(current.get('event_id'));saved_labels.setdefault(current.get('event_id'),set()).add(canonical_label(current.get('label')))
 # Also see direct saves that completed while the manifest was being replaced.
 for key in requested:
  current=read(examples/key/'review.json',{})
  if current.get('human_confirmed') and not current.get('deleted'):
   reviewed.add(key);saved_labels.setdefault(key,set()).add(canonical_label(current.get('label')))
 closed=[];confirmed=[];acknowledged=[];pending_diagnostics=[]
 for item in items:
  key=item['id']
  if item['kind']=='detection':done=key in reviewed
  else:
   target=data/'videos'/key;quick=read(target/'quick-frame-review.json',{});meta=read(target/'video.json',{});annotations=read(target/'annotations.json',[])
   done=bool(quick.get('annotation_id') and any(a.get('id')==quick['annotation_id'] for a in annotations)) or read(target/'review.json',{}).get('completed',False) or read(data/'reviewed-videos.json',{}).get(meta.get('sha256'),{}).get('completed',False)
  request=item.get('request_id');pending_label=item.get('pending_label')
  if request and re.fullmatch('[a-f0-9]{32}',str(request)):
   receipt={}
   if item['kind']=='detection':
    audit=hashlib.sha256(('station_web_review:quick-label:'+request).encode()).hexdigest()
    receipt=read(data/'email-reviews/history'/(audit+'.json'),{})
    saved=receipt.get('event_id')==key and canonical_label(receipt.get('label'))==canonical_label(pending_label) and receipt.get('human_confirmed') and not receipt.get('deleted')
   else:
    saved=quick.get('request_id')==request and canonical_label(quick.get('label'))==canonical_label(pending_label)
   if saved:acknowledged.append(dict(id=key,kind=item['kind'],request_id=request))
   pending_diagnostics.append(dict(id=key,kind=item['kind'],request_id=request,pending_label=pending_label,receipt_confirmed=bool(saved),currently_reviewed=bool(done),saved_labels=sorted(v for v in saved_labels.get(key,set()) if isinstance(v,str))))
  # Archived cards are no longer queue work. No save is acknowledged unless
  # a matching annotation or original receipt exists.
  if done or (item['kind']=='video' and meta.get('media_expired')):
   closed.append(item)
   labels=saved_labels.get(key,set()) if item['kind']=='detection' else {canonical_label(a.get('label')) for a in annotations if a.get('id')==quick.get('annotation_id')}
   if len(labels)==1 and next(iter(labels)) in LABELS:confirmed.append(dict(item,label=next(iter(labels))))
 if pending_diagnostics:
  diagnostic=data/'pending-label-diagnostics.json'
  if read(diagnostic,[])!=pending_diagnostics:
   import uuid
   temp=diagnostic.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(pending_diagnostics));temp.replace(diagnostic)
 return dict(reviewed=closed,confirmed=confirmed,acknowledged=acknowledged)
