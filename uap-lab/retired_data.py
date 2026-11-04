"""Retire unwanted categories permanently; remove only their unshared media."""
import argparse,fcntl,json,os,re,shutil,time,uuid
from pathlib import Path
from classification_taxonomy import canonical_label,LABELS
RETIRED={'tree','landscape','mountain','house','antenna','telephone_pole','background'}
def read(path,default=None):
 try:return json.loads(path.read_text())
 except FileNotFoundError:return default

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
 with tmp.open('w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
 tmp.replace(path)

def ids(data,records=None):
 data=Path(data);records=records if records is not None else read(data/'email-reviews/training-manifest.json',{}).get('examples',[])
 marker=read(data/'retired-objects.json',{});samples=set(marker.get('samples',[]));events=set(marker.get('events',[]));valid=set();retired=set()
 for r in records:
  event=r.get('event_id');sample=r.get('sample_id') or event
  if canonical_label(r.get('label')) in LABELS and r.get('human_confirmed') and not r.get('deleted'):valid.add(event)
  if r.get('label') in RETIRED or r.get('retired'):
   samples.add(sample);retired.add(event)
   if sample==event:events.add(event)
 events.update(retired-valid)
 return {v for v in samples if isinstance(v,str)},{v for v in events if isinstance(v,str)}

def visible(row,samples,events):
 if row.get('kind')=='detection':return row['id'] not in events
 if row.get('kind')=='review':return row.get('sample_id',row['id']) not in samples
 return True

def plan(data):
 data=Path(data);records=read(data/'email-reviews/training-manifest.json',{}).get('examples',[]);samples,events=ids(data,records)
 valid_events={r.get('event_id') for r in records if r.get('human_confirmed') and not r.get('deleted') and canonical_label(r.get('label')) in LABELS}
 active={g.get('id') for g in read(data.parent/'notifications/outbox/producer-state.json',{}).get('groups',[])}
 media_events=events-valid_events-active;files=[]
 for key in samples:
  if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid retired sample ID')
  folder=data/'email-reviews/examples'/key
  if folder.is_symlink():raise ValueError('Unsafe retired sample path')
  for p in folder.rglob('*'):
   if p.is_symlink():raise ValueError('Unsafe retired media link')
   if p.is_file() and p.name!='review.json':files.append(p)
 for key in media_events:
  if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid retired event ID')
  folder=data.parent/'notifications/outbox'/key
  if folder.is_symlink():raise ValueError('Unsafe retired event path')
  for p in folder.rglob('*'):
   if p.is_symlink():raise ValueError('Unsafe retired media link')
   if p.is_file():files.append(p)
 return dict(samples=sorted(samples),events=sorted(events),media_events=sorted(media_events),protected_shared_events=sorted(events&valid_events),files=files,records=records)

def retire(data,apply=False):
 data=Path(data)
 with (data/'email-reviews/review.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);p=plan(data);sizes={str(f):f.stat().st_size for f in p['files']}
  result=dict(samples=len(p['samples']),event_cards=len(p['events']),event_bundles=len(p['media_events']),protected_shared_events=len(p['protected_shared_events']),files=len(sizes),bytes=sum(sizes.values()),applied=apply)
  if not apply:return result
  audit=data/'retirement-history'/str(time.time_ns());audit.mkdir(parents=True)
  save(audit/'plan.json',dict(result,samples=p['samples'],events=p['events'],files=sizes))
  save(data/'retired-objects.json',dict(schema=1,updated_epoch=time.time(),samples=p['samples'],events=p['events']))
  # Persist tombstones before deleting pixels; retries and imports cannot resurrect cards.
  updated=[];sample_ids=set(p['samples'])
  for r in p['records']:
   key=r.get('sample_id') or r.get('event_id')
   if key in sample_ids:
    r=dict(r,deleted=True,retired=True,retired_epoch=time.time(),retirement_reason='User removed irrelevant landscape/structure categories')
    save(data/'email-reviews/examples'/key/'review.json',r)
   updated.append(r)
  save(data/'email-reviews/training-manifest.json',dict(updated_epoch=time.time(),examples=updated,classes=sorted(LABELS)))
  for f in p['files']:f.unlink(missing_ok=True)
  for key in p['media_events']:
   folder=data.parent/'notifications/outbox'/key
   if folder.exists():shutil.rmtree(folder)
  index=data.parent/'notifications/outbox/review-queue.sqlite'
  if index.exists():
   import sqlite3
   with sqlite3.connect(index) as db:db.executemany('DELETE FROM entries WHERE id=?',[(k,) for k in p['media_events']])
  cached=read(data/'object-library-cache.json',None)
  if cached:
   cached['items']=[row for row in cached['items'] if visible(row,sample_ids,set(p['events']))];save(data/'object-library-cache.json',cached)
  save(audit/'result.json',result);return result

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--data',required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args();print(json.dumps(retire(args.data,args.apply)))
