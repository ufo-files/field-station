"""Pin native alert context independently of the expiring capture spool."""
import hashlib,json,os,re
from pathlib import Path
from spool_events import atomic

def backed_up(root,event,folder):
 receipt=folder/'review-source.json'
 if not receipt.exists():return False
 record=json.loads(receipt.read_text());generation=event.get('generation','')
 if not re.fullmatch(r'run-[a-f0-9]+',generation) or record.get('generation')!=generation:return False
 evidence=Path(root)/'notifications/evidence'/generation
 for entry in record.get('segments',[]):
  if not re.fullmatch(r'segment-\d+\.mkv',entry['file']):return False
  p=evidence/entry['file']
  if p.is_symlink() or not p.is_file() or p.stat().st_size!=entry['bytes']:return False
 return bool(record.get('segments'))

def preserve(root):
 root=Path(root);copied=0;protected=0;errors=[];verified=set();indices={}
 for p in (root/'notifications/outbox').glob('*/event.json'):
  try:
   event=json.loads(p.read_text());delivery=p.parent/'delivery.json';state=json.loads(delivery.read_text()).get('state') if delivery.exists() else 'queued'
   if event.get('test') or state in ('cancelled','suppressed','expired') or (p.parent/'review-clip.json').exists():continue
   if backed_up(root,event,p.parent):continue
   generation=event['generation']
   if not re.fullmatch(r'run-[a-f0-9]+',generation):raise ValueError('Invalid alert generation')
   spool=root/'capture-spool'/generation
   if generation not in indices:indices[generation]=[json.loads(line) for line in (spool/'segments-index.jsonl').read_text().splitlines()]
   selected=[e for e in indices[generation] if e['end']>=event['pts_seconds']-5 and e['start']<=event['pts_seconds']+5]
   if not selected or (max(e['end'] for e in selected)<event['pts_seconds']+5 and not (spool/'closed.json').exists()):continue
   target=root/'notifications/evidence'/generation;target.mkdir(parents=True,exist_ok=True)
   for e in selected:
    name=e['file']
    if not re.fullmatch(r'segment-\d+\.mkv',name):raise ValueError('Invalid native segment')
    dest=target/name;source=spool/name
    if source.is_symlink() or dest.is_symlink():raise ValueError('Unsafe alert evidence')
    if not dest.exists():os.link(source,dest);copied+=1
    if str(dest) not in verified:
     if hashlib.sha256(dest.read_bytes()).hexdigest()!=e['sha256']:raise ValueError('Alert source checksum mismatch')
     with dest.open('rb') as f:os.fsync(f.fileno())
     verified.add(str(dest))
   atomic(p.parent/'review-source.json',dict(generation=generation,segments=selected));protected+=1
  except Exception as exc:errors.append(dict(alert=p.parent.name,error=str(exc)))
 return dict(protected_alerts=protected,linked_segments=copied,errors=errors)
