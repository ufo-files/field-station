"""Offline correction selection. Fit on calibration only; retain incumbent elsewhere."""
CUTOFFS=(.8,.85,.9,.93,.95,.97,.99,.995,.999)

def select_rules(baseline,proposed):
 old={p['origin']:p for p in baseline};rules=[]
 if set(old)!={p['origin'] for p in proposed}:raise ValueError('Calibration identities differ')
 if any(p['truth']!=old[p['origin']]['truth'] or p['group']!=old[p['origin']]['group'] for p in proposed):raise ValueError('Calibration labels or groups differ')
 for label in ('anomalous','not_anomalous'):
  options=[]
  for cutoff in CUTOFFS:
   accepted=[p for p in proposed if p['raw_label']==label and p['score']>=cutoff and p.get('native_eligible',True)]
   changed=[p for p in accepted if old[p['origin']]['label']!=label]
   harm=[p for p in changed if p['truth']!=label]
   improvements=[p for p in changed if p['truth']==label]
   groups={p['group'] for p in improvements}
   if not harm and len(improvements)>=5 and len(groups)>=3:
    options.append(dict(label=label,cutoff=cutoff,corrected=len(improvements),groups=len(groups),false_overrides=0))
  if options:rules.append(max(options,key=lambda r:(r['groups'],r['corrected'],r['cutoff'])))
 return rules

def apply_rules(baseline,proposed,rules):
 by_id={p['origin']:p for p in proposed};cutoffs={r['label']:r['cutoff'] for r in rules};result=[]
 if set(by_id)!={p['origin'] for p in baseline}:raise ValueError('Evaluation identities differ')
 for old in baseline:
  p=by_id[old['origin']]
  if p['truth']!=old['truth'] or p['group']!=old['group']:raise ValueError('Evaluation labels or groups differ')
  accept=p['raw_label'] in cutoffs and p['score']>=cutoffs[p['raw_label']] and p.get('native_eligible',True)
  result.append(dict(old,label=p['raw_label'] if accept else old['label'],correction_applied=accept and p['raw_label']!=old['label']))
 return result
