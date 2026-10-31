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

def detections(data,before='',limit=100):
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
 release=read(root.parent/'active-model-release.json',{})
 try:
  with os.scandir(root) as stream:keys=[e.name for e in stream if re.fullmatch('[a-f0-9]{32}',e.name) and (not boundary or e.name<boundary)]
 except FileNotFoundError:keys=[]
 keys.sort(reverse=True);rows=[];scanned=0;last=None
 for key in keys:
  path=root/key/'event.json';scanned+=1;last=key
  if key not in reviewed and read(path.parent/'delivery.json',{}).get('state') not in ('cancelled','suppressed','expired'):
   e=read(path,{})
   obsolete=release.get('state')=='deployed' and release.get('health_verified') and e.get('model')!=release.get('version') and e.get('created_epoch',float('inf'))<=release['deployed_epoch']
   name=e.get('native_crop','native-object.png')
   if not obsolete and name in ('native-object.png','object.png') and (path.parent/name).is_file():
    rows.append(dict(kind='detection',id=key,created=float(e.get('created_epoch',0)),suggested_label=e.get('classification','unknown'),image_url='/api/label-queue/image?id='+key,frame_url='/api/label-queue/image?full=1&id='+key,review_url='/email-review?id='+key))
  if len(rows)>=limit or scanned>=500:break
 more=scanned<len(keys);cursor=last if last and more else None
 return dict(items=rows,total=len(rows) if not before and not more else None,next_cursor=cursor,labels=sorted(LABELS))

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
  if m and not m.get('media_expired') and sha not in omitted and not reviewed.get(sha,{}).get('completed') and not read(target/'training-excluded.json',{}).get('excluded') and not read(target/'review.json',{}).get('completed') and (target/'source').is_file():
   items.append(dict(kind='video',id=key,title=m.get('name','Recorded video'),image_url='/api/label-queue/video-image?id='+key,review_url='/?view=label&video='+key))
  if len(items)>=limit or scanned>=500:break
 return dict(items=items,next_cursor=last if scanned<len(keys) else None,total=len(items) if not before and scanned==len(keys) else None)

def listing(data,before='',limit=100,source='all'):
 limit=max(1,min(100,int(limit)))
 if source not in ('all','detections','videos'):raise ValueError('Invalid queue')
 phase,key=before.split(':',1) if ':' in before else ('d',before)
 if phase not in ('d','v'):raise ValueError('Invalid cursor')
 if source=='videos' or phase=='v':
  result=videos(data,key,limit);result['next_cursor']='v:'+result['next_cursor'] if result['next_cursor'] else None
 else:
  result=detections(data,key,limit)
  if result['next_cursor']:result['next_cursor']='d:'+result['next_cursor']
  elif source=='all':
   if len(result['items'])==limit:result['next_cursor']='v:';result['total']=None
   else:
    rest=videos(data,'',limit-len(result['items']));result['items']+=rest['items'];result['next_cursor']='v:'+rest['next_cursor'] if rest['next_cursor'] else None
    result['total']=len(result['items']) if not before and not result['next_cursor'] else None
 if source=='all' and before:result['total']=None
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
