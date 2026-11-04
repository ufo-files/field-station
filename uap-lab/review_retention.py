"""Keep reviewed training crops; retire other media after its last evidence use."""
import bisect,collections,fcntl,hashlib,json,os,re,time
from pathlib import Path
from retired_data import save

def read(path,default=None):
 # Missing-file probes on the capture SSD can stall for seconds per folder.
 # Listing the small metadata directory avoids that path; never cache results.
 path=Path(path)
 try:
  if path.name not in {'review.json','event.json','manifest.json','video.json','buffer-state.json','training-manifest.json'} and path.name not in os.listdir(path.parent):return default
  return json.loads(path.read_text())
 except (OSError,ValueError):return default

def records(root,name):
 # These metadata files exist in their respective record directories. Avoid
 # glob's per-directory enumeration before opening the file directly.
 try:children=list(Path(root).iterdir())
 except FileNotFoundError:return []
 return [folder/name for folder in children if not folder.name.startswith('.')]

from backlog_media import MEDIA

def review_fingerprint(rows):
 return hashlib.sha256(json.dumps(sorted((r.get('sample_id',r['event_id']),r['reviewed_epoch'],r.get('deleted',False)) for r in rows)).encode()).hexdigest()

def cycle(data,sessions,groups,apply=True):
 """Run inside the archive export loop, after collecting current review groups."""
 data=Path(data);sessions=Path(sessions);root=data.parent;outbox=root/'notifications/outbox'
 reviews=data/'email-reviews';reviews.mkdir(exist_ok=True)
 with (data/'review-media.lock').open('a') as lease:
  try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return dict(busy=True)
  return _cycle(data,sessions,groups,apply)

def _cycle(data,sessions,groups,apply=True):
 from contextlib import contextmanager
 review_manifest=data/'email-reviews/training-manifest.json'
 def version():return review_manifest.stat().st_mtime_ns if review_manifest.exists() else None
 snapshot=version();latest_version=None;latest_reviews={}
 @contextmanager
 def guard(event_key=None):
  nonlocal latest_version,latest_reviews
  with (data/'email-reviews/review.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   current_version=version()
   if current_version!=snapshot:
    if latest_version!=current_version:
     latest_reviews=collections.defaultdict(list)
     for row in read(review_manifest,{}).get('examples',[]):latest_reviews[row.get('event_id')].append(row)
     latest_version=current_version
    if event_key is None:
     changed={key for key in set(latest_reviews)|set(by_event) if review_fingerprint(latest_reviews.get(key,[]))!=review_fingerprint(by_event.get(key,[]))}
     known={p.parent.name for p,e in event_entries}
     if changed & closed or changed-known:raise ValueError('Relevant reviews changed during cleanup; kept for next pass')
    elif review_fingerprint(latest_reviews.get(event_key,[]))!=review_fingerprint(by_event.get(event_key,[])):raise ValueError('This review changed during cleanup; kept for next pass')
   yield
 def persist(path,value):
  if apply:save(path,value)
 class CropChecks:
  def __init__(self):self.entries={};self.checked={}
  def get(self,key):
   if key not in self.checked:
    crop,digest=self.entries.get(key,(None,None))
    self.checked[key]=bool(crop and crop.is_file() and not crop.is_symlink() and hashlib.sha256(crop.read_bytes()).hexdigest()==digest)
   return self.checked[key]
 root=data.parent;outbox=root/'notifications/outbox';by_event=collections.defaultdict(list);valid=CropChecks();errors=[]
 for p in records(data/'email-reviews/examples','review.json'):
  r=read(p,{})
  if r.get('event_id'):by_event[r['event_id']].append(r)
  if r.get('human_confirmed') and not r.get('deleted'):
   crop=p.parent/'native-object.png'
   valid.entries[r.get('sample_id',r['event_id'])]=(crop,r.get('native_crop_sha256'))
 cutoff=read(data/'review-queue-cleared.json',{}).get('cutoff_epoch',float('-inf'))
 active={g.get('id') for g in read(outbox/'producer-state.json',{}).get('groups',[])}
 archived={};verified_sessions=set()
 for sid,rows in groups.items():
  folder=sessions/sid;manifest=read(folder/'manifest.json',{});receipt=manifest.get('internet_archive',{});decision=read(folder/'archive-decision.json',{})
  from archive_exports import digest
  revision=digest(rows)
  if receipt.get('state')!='cleaned' or not receipt.get('verified_at') or decision.get('review_revision')!=revision:continue
  # The upload receipt must include the exact annotation sidecar, not only video.
  sidecar=folder/'review-annotations.json';entry=next((e for e in receipt.get('files',[]) if e.get('name')=='review-annotations.json'),{})
  if not sidecar.is_file() or read(sidecar,{}).get('review_revision')!=revision or hashlib.sha256(sidecar.read_bytes()).hexdigest()!=entry.get('sha256'):continue
  if any(not valid.get(a.get('sample_id',a.get('event_id'))) for g in rows if g['kind']=='alert_web' for a in g['annotations']):continue
  if any(review_fingerprint(g['annotations'])!=review_fingerprint([a for a in by_event.get(g['id'],[]) if a.get('human_confirmed') and not a.get('deleted')]) for g in rows if g['kind']=='alert_web'):continue
  if read(root/'retention-policy.json',{}).get('local_anomalous_copy_required'):
   copy=read(folder/'archive-copy.json',{})
   expected=[{k:e.get(k) for k in ('name','bytes','sha256')} for e in receipt.get('files',[])]
   if not copy.get('verified') or copy.get('identifier')!=receipt.get('identifier') or copy.get('files')!=expected:continue
  verified_sessions.add(sid)
  for group in rows:
   if group['kind']=='alert_web':archived[group['id']]=(sid,group,receipt)
 closed=set();deleted=0;size=0;event_work=0
 audit=root/'retention/review-media.jsonl';audit.parent.mkdir(exist_ok=True)
 def unlink_media(folder,keep=()):
  nonlocal deleted,size
  if folder.is_symlink():raise ValueError('Unsafe media folder')
  paths=list(folder.rglob('*'))
  if any(p.is_symlink() for p in paths):raise ValueError('Unsafe media link')
  with (audit if apply else Path(os.devnull)).open('a') as log:
   for p in paths:
    if not p.is_file() or p in keep or not (p.suffix.lower() in MEDIA or p.name=='source'):continue
    n=p.stat().st_size;log.write(json.dumps(dict(path=str(p),bytes=n,epoch=time.time()))+'\n');log.flush();os.fsync(log.fileno()) if apply else None;
    if apply:p.unlink()
    deleted+=1;size+=n
 event_entries=[(p,read(p,{})) for p in records(outbox,'event.json')]
 event_entries.sort(key=lambda item:(item[1].get('created_epoch',0),item[0].parent.name))
 for p,event in event_entries:
  key=p.parent.name
  if not re.fullmatch('[a-f0-9]{32}',key) or key in active:continue
  rows=by_event.get(key,[]);current=[r for r in rows if r.get('human_confirmed') and not r.get('deleted')]
  negative=bool(current) and all(r.get('label')=='not_anomalous' for r in current)
  cleared=not current and (read(p.parent/'label-queue-dismissed.json',{}).get('dismissed') or event.get('created_epoch',float('inf'))<=cutoff)
  if not (negative or cleared or key in archived):continue
  fingerprint=review_fingerprint(rows)
  previous=read(p.parent/'local-media-retired.json',{})
  if event_work>=1000 and not previous:continue
  has_media=any((f.suffix.lower() in MEDIA or f.name=='source') and f.is_file() for f in p.parent.rglob('*'))
  if previous.get('review_fingerprint')==fingerprint and not has_media:
   closed.add(key);continue
  if current and not all(valid.get(r.get('sample_id',key)) for r in current):errors.append(dict(id=key,error='Training crop not verified'));continue
  if has_media:
   if event_work>=1000:continue
   event_work+=1
  try:
   marker=dict(epoch=time.time(),review_fingerprint=review_fingerprint(rows),reason='cleared' if cleared else 'reviewed_negative')
   if key in archived:
    sid,group,receipt=archived[key]
    # Store the exact export grouping so removal cannot trigger re-encoding.
    marker.update(reason='internet_archive_verified',session_id=sid,group=group,clip=read(p.parent/'review-clip.json',{}),url=receipt.get('url'))
   with guard(key):
    persist(p.parent/'local-media-retired.json',marker)
    unlink_media(p.parent);closed.add(key)
  except (OSError,ValueError) as exc:errors.append(dict(id=key,error=str(exc)))
 try:
  with guard():pass
 except ValueError:
  result=dict(epoch=time.time(),closed_events=len(closed),deleted_files=deleted,unlinked_bytes=size,verified_sessions=len(verified_sessions),shared_cleanup_deferred=True,errors=errors)
  persist(root/'retention/review-media-status.json',result);return result
 # Shared native segments can go only when every referencing event is closed.
 needed=set();candidates=set()
 for p in records(outbox,'review-source.json'):
  source=read(p,{});generation=source.get('generation','')
  if not re.fullmatch('run-[a-f0-9]+',generation):continue
  for e in source.get('segments',[]):
   name=e.get('file','')
   if re.fullmatch(r'segment-[0-9]+\.mkv',name):
    target=root/'notifications/evidence'/generation/name
    (candidates if p.parent.name in closed else needed).add(target)
 # Verified sessions no longer need duplicate playback, exports or local full video.
 # Keep reviewed frame pairs and label crops; they are the durable training evidence.
 video_index=collections.defaultdict(list)
 for p in records(data/'videos','video.json'):video_index[read(p,{}).get('provenance',{}).get('session_id')].append(p)
 eligible_sessions=set(verified_sessions)
 events_by_generation=collections.defaultdict(list);reviews_by_generation=collections.defaultdict(list)
 for p,e in event_entries:events_by_generation[e.get('generation')].append((e.get('pts_seconds',-100),p.parent.name))
 for key,rows in by_event.items():
  for row in rows:
   if row.get('human_confirmed') and not row.get('deleted'):reviews_by_generation[row.get('generation')].append((row.get('pts_seconds',-100),key))
 for mapping in (events_by_generation,reviews_by_generation):
  for values in mapping.values():values.sort()
 def between(mapping,gen,start,end):
  values=mapping.get(gen,[])
  return {key for pts,key in values[bisect.bisect_left(values,(start-5,'')):bisect.bisect_right(values,(end+5,'z'))]}
 cutoff=read(data/'review-queue-cleared.json',{}).get('cutoff_epoch',0)
 for manifest in records(sessions,'manifest.json'):
  m=read(manifest,{});sid=manifest.parent.name
  if m.get('state') not in ('completed','interrupted'):continue
  segments=read(manifest.parent/'buffer-state.json',{}).get('segments',[])
  if not segments:continue
  gen=m.get('spool_generation')
  if not isinstance(gen,str) or not re.fullmatch('run-[a-f0-9]+',gen):continue
  start=min(e['start'] for e in segments);end=max(e['end'] for e in segments)
  related=between(events_by_generation,gen,start,end)
  if not related<=closed:
   eligible_sessions.discard(sid);continue
  if sid in verified_sessions:continue
  # No detections is not an instruction to archive an automatic recording.
  # Analysis acknowledgments below still prevent deleting unprocessed video.
  if not related and m.get('capture_origin')!='provisional_motion':continue
  if not between(reviews_by_generation,gen,start,end)<=closed:continue
  if m.get('stopped_epoch',float('inf'))<=cutoff:
   eligible_sessions.add(sid);continue
  acknowledged=True
  for name in ('analysis-ack.json','recognition-ack.json'):
   ack=read(root/'capture-spool'/gen/name,{})
   if not ack.get('integrity_ok') or ack.get('generation')!=gen or ack.get('last_pts_seconds',-1)<end:acknowledged=False
  if acknowledged:eligible_sessions.add(sid)
 # Training crops must be usable before deleting their source recording.
 from PIL import Image
 from classification_taxonomy import canonical_label
 leases=read(data/'review-leases.json',{});active_videos=set()
 for p in records(data/'runs','run.json'):
  run=read(p,{})
  if run.get('state') not in ('complete','completed','failed','cancelled'):active_videos.add(run.get('video_id'))
 for sid in list(eligible_sessions):
  try:
   for p in video_index.get(sid,[]):
    if p.parent.name in active_videos or leases.get(p.parent.name,0)>time.time():raise ValueError('Video still in use')
    for a in read(p.parent/'annotations.json',[]):
     if sid not in verified_sessions and canonical_label(a.get('label'))!='not_anomalous':raise ValueError('Video annotation awaits archive verification')
     crop=p.parent/a['image']
     if crop.is_symlink() or crop.resolve().parent!=p.parent.resolve():raise ValueError('Unsafe training crop')
     with Image.open(crop) as image:image.verify()
  except (OSError,ValueError,KeyError):eligible_sessions.discard(sid)
 for manifest in records(sessions,'manifest.json'):
  if manifest.parent.name in eligible_sessions:continue
  gen=read(manifest,{}).get('spool_generation','')
  for entry in read(manifest.parent/'buffer-state.json',{}).get('segments',[]):
   needed.add(root/'notifications/evidence'/gen/entry['file'])
 with guard():
  with (audit if apply else Path(os.devnull)).open('a') as log:
   for p in candidates-needed:
    if p.is_symlink():errors.append(dict(path=str(p),error='Unsafe evidence link'));continue
    if p.is_file():
     n=p.stat().st_size;log.write(json.dumps(dict(path=str(p),bytes=n,epoch=time.time()))+'\n');log.flush();os.fsync(log.fileno()) if apply else None;
     if apply:p.unlink()
     deleted+=1;size+=n
 session_work=0
 for sid in sorted(eligible_sessions):
  folder=sessions/sid
  if read(folder/'review-media-retired.json',{}).get('complete'):continue
  if session_work>=250:break
  session_work+=1
  try:
   with guard():
    keep=set(folder.glob('frames/reviewed-*/*.png'))
    linked=video_index.get(sid,[])
    unlink_media(folder,keep)
    for meta in linked:
     m=read(meta,{})
     if m.get('provenance',{}).get('session_id')!=sid:continue
     annotations=read(meta.parent/'annotations.json',[])
     keep={meta.parent/a['image'] for a in annotations if a.get('image')}
     if any(not p.is_file() for p in keep):raise ValueError('Reviewed video crop missing')
     unlink_media(meta.parent,keep);m['media_expired']=True;persist(meta,m)
    m=read(folder/'manifest.json',{});m['session_media_removed']=True;persist(folder/'manifest.json',m)
    queue=data/'provisional-queue'/(sid+'.json');job=read(queue,{})
    job.update(state='archived' if sid in verified_sessions else 'discarded',retention_reason='review_media_policy');persist(queue,job)
    persist(folder/'review-media-retired.json',dict(complete=True,epoch=time.time()))
  except (OSError,ValueError) as exc:errors.append(dict(id=sid,error=str(exc)))
 result=dict(epoch=time.time(),closed_events=len(closed),deleted_files=deleted,unlinked_bytes=size,verified_sessions=len(verified_sessions),errors=errors)
 persist(root/'retention/review-media-status.json',result);return result


def prune_private(archive,retired,apply=True):
 """Retire only completed private copies of sessions already locally retired."""
 archive=Path(archive);removed=0;size=0
 if not archive.is_dir() or archive.is_symlink():return dict(files=0,bytes=0)
 with (archive/'receiver.lock').open('a') as lease:
  try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return dict(busy=True,files=0,bytes=0)
  for p in records(archive,'manifest.json'):
   unit=read(p,{});folder=p.parent;receipt=read(folder/'receipt.json',{});target=folder/'recording.tar'
   if unit.get('session') not in retired or not receipt.get('verified') or receipt.get('session')!=unit.get('session'):continue
   fingerprint=hashlib.sha256(json.dumps(unit,sort_keys=True,separators=(',',':')).encode()).hexdigest()
   if folder.name!=fingerprint or receipt.get('fingerprint')!=fingerprint or folder.is_symlink() or target.is_symlink():continue
   if target.is_file():
    n=target.stat().st_size
    if apply:
     save(folder/'retired.json',dict(epoch=time.time(),reason='review_media_policy',session=unit['session'],bytes=n))
     target.unlink()
    removed+=1;size+=n
 return dict(files=removed,bytes=size)

def watch(data,sessions):
 """Run independently so a slow archive encode cannot starve disk cleanup."""
 while True:
  try:
   groups=read(Path(data)/'archive-review-groups.json',{}).get('groups',{})
   cycle(data,sessions,groups)
   retired={p.parent.name for p in records(sessions,'review-media-retired.json') if read(p,{}).get('complete') and (not read(p.parent/'manifest.json',{}).get('internet_archive',{}).get('verified_at') or read(p.parent/'archive-copy.json',{}).get('verified'))}
   for archive in read(Path(data).parent/'retention-policy.json',{}).get('review_archive_roots',[]):
    result=prune_private(archive,retired)
    if result.get('files'):print('Retired private archive copies:',json.dumps(result),flush=True)
  except Exception as exc:print('Reviewed media retention:',str(exc),flush=True)
  time.sleep(60)
