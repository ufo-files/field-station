"""Delete cleared, unreviewed media; retain audit records and shared originals."""
import json,re,os,fcntl
from pathlib import Path
from retired_data import read,save

MEDIA={'.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv','.ts','.wav','.flac','.avi'}

def cleanup(data,audit):
 """Lock and recheck each object; allow review saves between deletions."""
 data=Path(data);audit=Path(audit)
 reviews=data/'email-reviews';reviews.mkdir(parents=True,exist_ok=True)
 manifest=reviews/'training-manifest.json';stamp=object();reviewed=set()
 def refresh_reviews():
  nonlocal stamp,reviewed
  current=manifest.stat().st_mtime_ns if manifest.exists() else None
  if current==stamp:return
  try:
   if (reviews/'examples').stat().st_mtime_ns>current:raise ValueError('Stale index')
   rows=read(manifest,{})['examples']
  except (OSError,KeyError,TypeError,ValueError):
   from review_retention import load_records
   rows=[r for p,r in load_records(reviews/'examples','review.json')]
  reviewed={r.get('event_id') for r in rows if r.get('human_confirmed') and not r.get('deleted')};stamp=current
 outbox=data.parent/'notifications/outbox'
 active={g.get('id') for g in read(outbox/'producer-state.json',{}).get('groups',[])}
 deleted=0;size=0;protected=[];deferred=[]
 with (audit/'media-deletions.jsonl').open('a') as log:
  for line in (audit/'actions.jsonl').read_text().splitlines():
   row=json.loads(line);key=row['id']
   if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid cleared ID')
   from review_playback import event_lease
   from contextlib import nullcontext
   with event_lease(outbox/key) if row['kind']=='detection' else nullcontext(True) as available,(reviews/'review.lock').open('a') as lock:
    if not available:deferred.append(key);continue
    fcntl.flock(lock,fcntl.LOCK_EX);refresh_reviews()
    if row['kind']=='detection':
     target=outbox/key
     if key in reviewed or read(target/'review-completion.json',{}).get('completed'):
      protected.append(key);continue
     if key in active:deferred.append(key);continue
    elif row['kind']=='video':
     target=data/'videos'/key;review=read(target/'review.json',{})
     if read(target/'annotations.json',[]) or review.get('completed') or review.get('reviewed_at'):
      protected.append(key);continue
    else:raise ValueError('Invalid cleared kind')
    if target.is_symlink():raise ValueError('Unsafe cleared folder')
    paths=list(target.rglob('*'))
    if row['kind']=='detection':
     from review_playback import media_dir
     playback=media_dir(data,key)
     if playback!=target:
      if playback.is_symlink():raise ValueError('Unsafe review media folder')
      paths+=list(playback.rglob('*'))
    if any(p.is_symlink() for p in paths):deferred.append(key);continue
    for p in paths:
     if not p.is_file() or not (p.suffix.lower() in MEDIA or p.name=='source'):continue
     n=p.stat().st_size
     log.write(json.dumps(dict(path=str(p),bytes=n))+'\n');log.flush()
     p.unlink();deleted+=1;size+=n
 result=dict(media_deleted=True,media_files_deleted=deleted,media_bytes_deleted=size,media_protected=len(protected),media_deferred=len(deferred))
 save(audit/'media-result.json',result)
 return result
