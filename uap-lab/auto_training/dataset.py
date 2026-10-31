"""Combine fixed baseline evidence with current reviews and persistent recording splits."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
from candidate_dataset import group_rows,assign_splits

def build(base,reviews,out,ledger):
 base,reviews,out,ledger=map(Path,(base,reviews,out,ledger));original=json.loads((base/'dataset.json').read_text());current=json.loads((reviews/'reviews.json').read_text());frozen=json.loads(ledger.read_text()) if ledger.exists() else {};rows=[];aliases={}
 for row in original['samples']:
  for alias in [row['group'],*row.get('group_aliases',[])]:aliases[alias]=row['group']
 for root,source,is_base in ((base,original['samples'],True),(reviews,current['samples'],False)):
  for row in source:
   path=root/row['image']
   if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe training image')
   with Image.open(path) as im:
    im=im.convert('RGB');digest=hashlib.sha256(f'{im.width}x{im.height}:RGB:'.encode()+im.tobytes()).hexdigest()
   if digest!=row['pixel_sha256']:raise ValueError('Training image checksum changed')
   group=aliases.get(row['group'],row['group']);fixed=row['split'] if is_base else frozen.get(group)
   rows.append(dict(row,source=str(path),group=group,fixed_split=fixed))
 rows,quarantine=group_rows(rows);coverage,blockers=assign_splits(rows)
 baseline_classes={r['label'] for r in original['samples']}
 deferred_classes={label for label,roles in coverage.items() if label not in baseline_classes and any(n<2 for n in roles.values())}
 deferred=[dict(origin=r['origin'],label=r['label'],reason='New class awaits independent train/calibration/test coverage') for r in rows if r['label'] in deferred_classes]
 if deferred:
  rows=[r for r in rows if r['label'] not in deferred_classes]
  coverage,blockers=assign_splits(rows)

 for row in rows:
  for alias in row['group_aliases']:frozen[alias]=row['split']
 out.mkdir(parents=True);(out/'images').mkdir();samples=[]
 for i,row in enumerate(rows):
  name=f'images/{i:06d}.png'
  with Image.open(row['source']) as im:im.convert('RGB').save(out/name)
  samples.append({k:v for k,v in dict(row,image=name).items() if k!='source'})
 ledger.parent.mkdir(parents=True,exist_ok=True);temp=ledger.with_suffix('.tmp');temp.write_text(json.dumps(frozen));temp.replace(ledger)
 fingerprint=hashlib.sha256(json.dumps(samples,sort_keys=True).encode()).hexdigest()
 result=dict(schema_version=1,fingerprint=fingerprint,review_fingerprint=current['fingerprint'],baseline_fingerprint=original['fingerprint'],classes=sorted({r['label'] for r in samples}),samples=samples,counts=dict(Counter(r['label'] for r in samples)),independent_groups=coverage,blockers=blockers,quarantine=quarantine,deferred=deferred)
 (out/'dataset.json').write_text(json.dumps(result));return result
