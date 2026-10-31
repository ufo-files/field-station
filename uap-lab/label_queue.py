"""Fast human labeling of saved detection crops; never auto-completes a session."""
import hashlib,json,re,time,os
from pathlib import Path
from email_training import LABELS,store_review

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

def listing(data,before='',limit=100):
 data=Path(data);limit=max(1,min(100,int(limit)));reviewed=set()
 for p in (data/'email-reviews/examples').glob('*/review.json'):
  r=read(p,{})
  if r.get('human_confirmed') and not r.get('deleted'):reviewed.add(r.get('event_id'))
 boundary=''
 if before:
  boundary=before.rsplit(':',1)[-1]
  if not re.fullmatch('[a-f0-9]{32}',boundary):raise ValueError('Invalid cursor')
 # Stable IDs avoid rescanning timestamps for every historical event. Paging is
 # independent of deletions or new reviews, and only this batch reads receipts.
 root=data.parent/'notifications/outbox'
 try:
  with os.scandir(root) as stream:keys=[e.name for e in stream if re.fullmatch('[a-f0-9]{32}',e.name) and (not boundary or e.name<boundary)]
 except FileNotFoundError:keys=[]
 keys.sort(reverse=True);rows=[];scanned=0;last=None
 for key in keys:
  path=root/key/'event.json';scanned+=1;last=key
  if key not in reviewed and read(path.parent/'delivery.json',{}).get('state') not in ('cancelled','suppressed','expired'):
   e=read(path,{})
   name=e.get('native_crop','native-object.png')
   if name in ('native-object.png','object.png') and (path.parent/name).is_file():
    rows.append(dict(id=key,created=float(e.get('created_epoch',0)),suggested_label=e.get('classification','unknown'),image_url='/api/label-queue/image?id='+key,frame_url='/api/label-queue/image?full=1&id='+key,review_url='/email-review?id='+key))
  if len(rows)>=limit or scanned>=500:break
 more=scanned<len(keys);cursor=last if last and more else None
 return dict(items=rows,total=len(rows) if not before and not more else None,next_cursor=cursor,labels=sorted(LABELS))

def label(data,body):
 data=Path(data);key=body['id'];target=folder(data,key);category=body.get('label');request=body.get('request_id','')
 if category not in LABELS:raise ValueError('Choose a valid category')
 if not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('Invalid request ID')
 message='quick-label:'+request
 existing=read(data/'email-reviews/examples'/key/'review.json',{})
 if existing.get('message_id')==message and existing.get('label')==category:return dict(saved=True,id=key,label=category)
 for p in (data/'email-reviews/examples').glob('*/review.json'):
  r=read(p,{})
  if r.get('event_id')==key and r.get('human_confirmed') and not r.get('deleted'):raise ValueError('This detection has already been reviewed. Open its video to change the label.')
 e=read(target/'event.json',{});path=target/e.get('native_crop','native-object.png')
 if path.is_symlink() or path.resolve().parent!=target.resolve():raise ValueError('Invalid crop')
 crop=path.read_bytes();digest=hashlib.sha256(crop).hexdigest()
 if digest!=e.get('native_crop_sha256'):raise ValueError('Original crop checksum does not match')
 record=dict(schema=1,event_id=key,sample_id=key,message_id=message,reviewed_epoch=time.time(),label=category,human_confirmed=True,source='station_web_review',generation=e['generation'],sequence=e.get('sequence'),pts_seconds=e['pts_seconds'],bounds=e['bounds'],model=e['model'],native_crop_sha256=digest,binary_anomalous=category=='anomalous',multiclass_ready=True,reviewer='station_web_ui')
 clip=read(target/'review-clip.json',{})
 if 'event_time' in clip:record['review_clip_time']=clip['event_time']
 from review_archive import invalidate_event
 invalidate_event(data,key);store_review(data,record,crop)
 return dict(saved=True,id=key,label=category)
