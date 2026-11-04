"""Delete cleared, unreviewed media; retain audit records and shared originals."""
import json,re,os
from pathlib import Path
from retired_data import read,save

MEDIA={'.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv','.ts','.wav','.flac','.avi'}

def cleanup(data,audit):
 """Caller holds email-reviews/review.lock. Recheck reviews before unlinking."""
 data=Path(data);audit=Path(audit)
 reviewed={r.get('event_id') for p in (data/'email-reviews/examples').glob('*/review.json') if (r:=read(p,{})).get('human_confirmed') and not r.get('deleted')}
 outbox=data.parent/'notifications/outbox'
 active={g.get('id') for g in read(outbox/'producer-state.json',{}).get('groups',[])}
 deleted=0;size=0;protected=[];deferred=[]
 with (audit/'media-deletions.jsonl').open('a') as log:
  for line in (audit/'actions.jsonl').read_text().splitlines():
   row=json.loads(line);key=row['id']
   if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid cleared ID')
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
   if any(p.is_symlink() for p in paths):deferred.append(key);continue
   for p in paths:
    if not p.is_file() or not (p.suffix.lower() in MEDIA or p.name=='source'):continue
    n=p.stat().st_size
    log.write(json.dumps(dict(path=str(p),bytes=n))+'\n');log.flush();os.fsync(log.fileno())
    p.unlink();deleted+=1;size+=n
 result=dict(media_deleted=True,media_files_deleted=deleted,media_bytes_deleted=size,media_protected=len(protected),media_deferred=len(deferred))
 save(audit/'media-result.json',result)
 return result
