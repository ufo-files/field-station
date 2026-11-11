"""Equal class and recording influence without discarding reviewed crops."""
from collections import Counter,defaultdict

def sample_weights(rows):
 if not rows:return []
 if any(r.get('pseudo_label') for r in rows):
  human=[r for r in rows if not r.get('pseudo_label')];pseudo=[dict(r,pseudo_label=False) for r in rows if r.get('pseudo_label')]
  if not human:raise ValueError('Hybrid training requires human/base training data')
  hw=sample_weights(human);pw=sample_weights(pseudo);budgets=defaultdict(float);totals=defaultdict(float)
  admitted=Counter(r['label'] for r in pseudo)
  for row,w in zip(human,hw):budgets[row['label']]+=w*.25*min(1,admitted[row['label']]/1000)
  for row,w in zip(pseudo,pw):totals[row['label']]+=w
  hi=iter(hw);pi=iter(w*budgets[r['label']]/totals[r['label']] for r,w in zip(pseudo,pw))
  return [next(pi) if r.get('pseudo_label') else next(hi) for r in rows]

 groups=defaultdict(set);pixels=defaultdict(set);copies=Counter()
 for r in rows:
  key=(r['label'],r['group']);pixel=r['pixel_sha256']
  groups[r['label']].add(r['group']);pixels[key].add(pixel);copies[key+(pixel,)]+=1
 scale=len(rows)/len(groups)
 return [scale/(len(groups[r['label']])*len(pixels[(r['label'],r['group'])])*copies[(r['label'],r['group'],r['pixel_sha256'])]) for r in rows]
