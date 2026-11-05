"""Delete a selected object and its unshared local media, with durable tombstones."""
import fcntl,re,time
from pathlib import Path
from retired_data import read,save
from backlog_media import MEDIA

def parse(key):
 if isinstance(key,str) and re.fullmatch('[a-f0-9]{32}',key):return 'review',key,key
 parts=key.split(':') if isinstance(key,str) else []
 if len(parts)!=3 or parts[0] not in ('review','video','preserved') or any(not re.fullmatch('[a-f0-9]{32}',v) for v in parts[1:]):raise ValueError('Invalid object')
 return parts

def omitted(data,key):
 return key in read(Path(data)/'omitted-objects.json',{}).get('objects',{})

def media(folder):
 if folder.is_symlink():raise ValueError('Unsafe object folder')
 paths=list(folder.rglob('*'))
 if any(p.is_symlink() for p in paths):raise ValueError('Unsafe object media')
 return [p for p in paths if p.is_file() and (p.suffix.lower() in MEDIA or p.name=='source')]

def omit(data,body):
 import detection_library as library
 data=Path(data);key=body.get('id');kind,event,sample=parse(key);reviews=data/'email-reviews';reviews.mkdir(parents=True,exist_ok=True)
 # Same lease order as retention: media lease before review lock.
 with library._SAVE_LOCK,(data/'review-media.lock').open('a') as lease,(reviews/'review.lock').open('a') as lock:
  try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Media cleanup is busy; retry shortly')
  fcntl.flock(lock,fcntl.LOCK_EX)
  markers=read(data/'omitted-objects.json',{'objects':{}});previous=markers['objects'].get(key,{})
  if previous.get('complete'):return dict(previous,id=key,deleted=True)
  files=[];now=time.time();deferred=False;shared=False
  if kind=='review':
   folder=reviews/'examples'/sample;outbox=data.parent/'notifications/outbox'/event
   if folder.is_symlink() or outbox.is_symlink():raise ValueError('Unsafe object folder')
   record=read(folder/'review.json',{});manifest=read(reviews/'training-manifest.json',{'examples':[]})
   if record and record.get('event_id')!=event:raise ValueError('Object does not belong to this detection')
   if not record and not (outbox/'event.json').is_file() and not previous:raise ValueError('Object no longer exists')
   rows=manifest.get('examples',[])
   shared=any(v.get('event_id')==event and v.get('sample_id',event)!=sample and v.get('human_confirmed') and not v.get('deleted') for v in rows)
   active={g.get('id') for g in read(outbox.parent/'producer-state.json',{}).get('groups',[])}
   files=media(folder)
   if not shared and event not in active:files+=media(outbox)
   deferred=not shared and event in active
   from review_archive import invalidate_event
   invalidate_event(data,event)
   markers['objects'][key]=dict(epoch=now,complete=False);save(data/'omitted-objects.json',markers)
   if record:
    record.update(deleted=True,retired=True,reviewed_epoch=now,omitted_epoch=now)
    save(folder/'review.json',record)
    rows=[record if v.get('sample_id',v.get('event_id'))==sample else v for v in rows]
    save(reviews/'training-manifest.json',dict(manifest,examples=rows,updated_epoch=now))
   retired=read(data/'retired-objects.json',{});samples=set(retired.get('samples',[]));events=set(retired.get('events',[]));samples.add(sample)
   if not shared:events.add(event)
   save(data/'retired-objects.json',dict(retired,samples=sorted(samples),events=sorted(events),updated_epoch=now))
   if not shared and outbox.exists():
    save(outbox/'label-queue-dismissed.json',dict(dismissed=True,deleted=True,epoch=now))
    save(outbox/'review-completion.json',dict(completed=False,reason='object_deleted',updated_epoch=now))
  else:
   import lab,labeled_frames
   folder=(data if kind=='video' else labeled_frames.preserved_root())/'videos'/event
   if folder.is_symlink():raise ValueError('Unsafe object folder')
   with lab._per_video_lock(lab._REVIEW_LOCKS,folder):
    annotations=read(folder/'annotations.json',[]);target=next((a for a in annotations if a['id']==sample),None) or previous.get('annotation')
    if not target and not previous:raise ValueError('Object no longer exists')
    kept=[a for a in annotations if a['id']!=sample];shared=bool(kept)
    files=media(folder)
    if shared:files=[p for p in files if target and p.name==target.get('image') and not any(a.get('image')==p.name for a in kept)]
    else:
     if read(data/'review-leases.json',{}).get(event,0)>now:raise ValueError('Video is in use; retry after review finishes')
     for path in (data/'runs').glob('*/run.json'):
      run=read(path,{})
      if run.get('video_id')==event and run.get('state') not in ('complete','completed','failed','cancelled'):raise ValueError('Video analysis is in progress; retry when it finishes')
    markers['objects'][key]=dict(epoch=now,complete=False,annotation=target);save(data/'omitted-objects.json',markers)
    meta=read(folder/'video.json',{})
    from review_archive import invalidate_session
    invalidate_session(meta.get('provenance',{}).get('session_id'))
    save(folder/'review.json',dict(completed=False,no_target=False,reason='object_deleted',invalidated_at=now))
    save(folder/'annotations.json',kept)
    if not kept:save(folder/'training-excluded.json',dict(excluded=True,omitted_at=now))
    # Delete while holding the annotation lock so a concurrent edit cannot reuse pixels.
    deleted_bytes=sum(p.stat().st_size for p in files if p.exists())
    for p in files:p.unlink(missing_ok=True)
  if kind=='review':
   deleted_bytes=sum(p.stat().st_size for p in files if p.exists())
   for p in files:p.unlink(missing_ok=True)
  result=dict(epoch=now,complete=True,deleted=True,id=key,files_deleted=len(files),bytes_deleted=deleted_bytes,shared_media_retained=shared,cleanup_pending=deferred)
  markers['objects'][key]=result;save(data/'omitted-objects.json',markers)
 library.invalidate()
 return result

def retry_pending(data):
 """Retention resumes interrupted deletion requests; no browser must stay open."""
 results=[]
 for key,state in read(Path(data)/'omitted-objects.json',{}).get('objects',{}).items():
  if state.get('complete'):continue
  try:results.append(omit(data,dict(id=key)))
  except (OSError,ValueError) as exc:results.append(dict(id=key,error=str(exc)))
  if len(results)>=5:break
 return results
