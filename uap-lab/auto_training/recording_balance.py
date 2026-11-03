"""Equal class and recording influence without discarding reviewed crops."""
from collections import Counter,defaultdict

def sample_weights(rows):
 if not rows:return []
 groups=defaultdict(set);pixels=defaultdict(set);copies=Counter()
 for r in rows:
  key=(r['label'],r['group']);pixel=r['pixel_sha256']
  groups[r['label']].add(r['group']);pixels[key].add(pixel);copies[key+(pixel,)]+=1
 scale=len(rows)/len(groups)
 return [scale/(len(groups[r['label']])*len(pixels[(r['label'],r['group'])])*copies[(r['label'],r['group'],r['pixel_sha256'])]) for r in rows]
