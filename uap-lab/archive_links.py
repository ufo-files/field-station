"""Attach verified Archive destinations to the exact human-reviewed objects."""
import hashlib,json,re
from pathlib import Path
from label_queue import read

def attach(data,rows):
 selected=[r for r in rows if r.get('human_reviewed') and r.get('label')=='anomalous']
 if not selected:return rows
 wanted={(r.get('kind'),r.get('video_id',r['id']),r.get('sample_id',r['id'])):r for r in selected}
 groups=read(Path(data)/'archive-review-groups.json',{}).get('groups',{})
 for sid,reviews in groups.items():
  if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):continue
  matches=[]
  for group in reviews:
   kind='review' if group.get('kind')=='alert_web' else 'video'
   for a in group.get('annotations',[]):
    key=(kind,group.get('id'),a.get('id',a.get('sample_id',group.get('id'))))
    if a.get('label')=='anomalous' and key in wanted:matches.append(wanted[key])
  if not matches:continue
  folder=Path(data).parent/'sessions'/sid
  decision=read(folder/'archive-decision.json',{});receipt=read(folder/'manifest.json',{}).get('internet_archive',{})
  revision=hashlib.sha256(json.dumps(reviews,sort_keys=True).encode()).hexdigest()
  url=receipt.get('url','')
  if not decision.get('bundle_ready') or decision.get('review_revision')!=revision or receipt.get('state') not in ('retaining','cleaned') or not receipt.get('verified_at'):continue
  if not re.fullmatch(r'https://archive\.org/details/[A-Za-z0-9_.-]+',url):continue
  download=bundle_url(folder)
  for row in matches:
   row['archive_url']=url
   if download:row['archive_bundle_url']=download
 return rows


def bundle_url(folder):
 """Only offer the current verified evidence bundle, never an older upload."""
 folder=Path(folder);decision=read(folder/'archive-decision.json',{});receipt=read(folder/'manifest.json',{}).get('internet_archive',{})
 identifier=receipt.get('identifier','')
 if not decision.get('bundle_ready') or receipt.get('state') not in ('retaining','cleaned') or not receipt.get('verified_at') or not re.fullmatch('[A-Za-z0-9_.-]+',identifier):return None
 sidecar=folder/'review-annotations.json'
 try:
  raw=sidecar.read_bytes();annotations=json.loads(raw)
 except (OSError,ValueError):return None
 entry=next((e for e in receipt.get('files',[]) if e.get('name')=='review-annotations.json'),{})
 if annotations.get('review_revision')!=decision.get('review_revision') or hashlib.sha256(raw).hexdigest()!=entry.get('sha256'):return None
 return 'https://archive.org/compress/'+identifier
