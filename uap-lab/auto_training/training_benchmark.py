"""Persist one random training-image sample per run, shared by both models."""
import json,random,secrets
from pathlib import Path
from collections import Counter

FIELDS=('image','origin','label','pixel_sha256')
def select(dataset,folder,size=500):
 path=Path(folder)/'training-benchmark.json'
 pool=[r for r in dataset['samples'] if r['split']=='train' and r['label'] in dataset['classes']]
 by_image={r['image']:r for r in pool}
 if not pool or len(by_image)!=len(pool):raise ValueError('Training benchmark needs unique training image paths')
 count=min(size,len(pool))
 if path.exists():
  saved=json.loads(path.read_text())
  if saved['dataset_fingerprint']!=dataset['fingerprint'] or saved['requested_count']!=size or len(saved['samples'])!=count:raise ValueError('Training benchmark identity changed')
  chosen=[]
  for entry in saved['samples']:
   row=by_image.get(entry['image'])
   if row is None or any(row.get(k)!=entry.get(k) for k in FIELDS):raise ValueError('Training benchmark image or label changed')
   chosen.append(row)
  if len({r['image'] for r in chosen})!=count:raise ValueError('Repeated benchmark image')
 else:
  seed=secrets.randbits(128);chosen=random.Random(seed).sample(pool,count)
  saved=dict(kind='random_training_sample',dataset_fingerprint=dataset['fingerprint'],requested_count=size,count=count,pool_count=len(pool),seed=str(seed),samples=[{k:r.get(k) for k in FIELDS} for r in chosen],description='Random sample of images used to train this candidate; measures training fit, not accuracy on unseen footage.')
  temp=path.with_suffix('.tmp');temp.write_text(json.dumps(saved,indent=2));temp.replace(path)
 return chosen,dict({k:v for k,v in saved.items() if k!='samples'},label_counts=dict(Counter(r['label'] for r in chosen)))
