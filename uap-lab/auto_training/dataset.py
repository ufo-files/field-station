"""Combine fixed baseline evidence with current reviews and persistent recording splits."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
from candidate_dataset import assign_splits

def reviewed_training_groups(rows):
 """All current reviews train; connected baseline evidence cannot stay held out."""
 parent={r['group']:r['group'] for r in rows}
 def find(g):
  while parent[g]!=g:parent[g]=parent[parent[g]];g=parent[g]
  return g
 seen={}
 for r in rows:
  for key in [('pixels',r['pixel_sha256']),('source',r.get('source_sha256'))]:
   if not key[1]:continue
   if key in seen:parent[find(r['group'])]=find(seen[key])
   else:seen[key]=r['group']
 components={}
 for r in rows:components.setdefault(find(r['group']),[]).append(r)
 result=[];audit=[]
 for members in components.values():
  aliases=sorted({r['group'] for r in members});group=hashlib.sha256('\n'.join(aliases).encode()).hexdigest()
  reviewed=[r for r in members if r['human_confirmed']]
  review_pixels={r['pixel_sha256'] for r in reviewed}
  fixed={r['fixed_split'] for r in members if r.get('fixed_split')}
  role='train' if reviewed or len(fixed)>1 else next(iter(fixed),'train')
  for r in members:
   if not r['human_confirmed'] and r['pixel_sha256'] in review_pixels:
    audit.append(dict(origin=r['origin'],reason='baseline_pixels_superseded_by_human_review'));continue
   result.append(dict(r,group=group,group_aliases=aliases,fixed_split=role))
 return result,audit

def build(base,reviews,out,ledger):
 base,reviews,out,ledger=map(Path,(base,reviews,out,ledger));original=json.loads((base/'dataset.json').read_text());current=json.loads((reviews/'reviews.json').read_text());frozen=json.loads(ledger.read_text()) if ledger.exists() else {};rows=[];aliases={}
 for row in original['samples']:
  for alias in [row['group'],*row.get('group_aliases',[])]:aliases[alias]=row['group']
 for root,source,is_base in ((base,original['samples'],True),(reviews,current['samples'],False)):
  for row in source:
   row=dict(row,label='landscape' if row['label']=='mountain' else row['label'])
   path=root/row['image']
   if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe training image')
   with Image.open(path) as im:
    im=im.convert('RGB');digest=hashlib.sha256(f'{im.width}x{im.height}:RGB:'.encode()+im.tobytes()).hexdigest()
   if digest!=row['pixel_sha256']:raise ValueError('Training image checksum changed')
   group=aliases.get(row['group'],row['group']);fixed=row['split'] if is_base else 'train'
   rows.append(dict(row,source=str(path),group=group,fixed_split=fixed,human_confirmed=not is_base))
 rows,quarantine=reviewed_training_groups(rows);coverage,validation_limits=assign_splits(rows)
 # Coverage limits affect validation claims, never admission to training.
 blockers=[f'Missing {role} split' for role in ('train','calibration','test') if not any(r['split']==role for r in rows)]
 deferred=[]

 for row in rows:
  for alias in row['group_aliases']:frozen[alias]=row['split']
 out.mkdir(parents=True);(out/'images').mkdir();samples=[]
 for i,row in enumerate(rows):
  name=f'images/{i:06d}.png'
  with Image.open(row['source']) as im:im.convert('RGB').save(out/name)
  samples.append({k:v for k,v in dict(row,image=name).items() if k!='source'})
 ledger.parent.mkdir(parents=True,exist_ok=True);temp=ledger.with_suffix('.tmp');temp.write_text(json.dumps(frozen));temp.replace(ledger)
 fingerprint=hashlib.sha256(json.dumps(samples,sort_keys=True).encode()).hexdigest()
 result=dict(schema_version=1,fingerprint=fingerprint,review_fingerprint=current['fingerprint'],baseline_fingerprint=original['fingerprint'],classes=sorted({r['label'] for r in samples}),samples=samples,counts=dict(Counter(r['label'] for r in samples)),independent_groups=coverage,blockers=blockers,quarantine=quarantine,deferred=deferred,validation_limits=validation_limits,human_training_counts=dict(Counter(r['label'] for r in samples if r['human_confirmed'])),review_policy='All current human-confirmed frames train; overlapping baseline groups are removed from holdout')
 (out/'dataset.json').write_text(json.dumps(result));return result
