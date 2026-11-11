"""Human authority and conservative pseudo-label admission for the shadow lane."""
import math
LABELS={'anomalous','not_anomalous'}
def pseudo_label(views,confidence=.995):
 if len(views)<3:return None
 labels=[]
 for scores in views:
  if set(scores)!=LABELS or any(not math.isfinite(v) or not 0<=v<=1 for v in scores.values()):return None
  label=max(scores,key=scores.get)
  if scores[label]<confidence:return None
  labels.append(label)
 return labels[0] if len(set(labels))==1 else None

def eligible_pseudo(human,pseudo):
 origins={r['origin'].removeprefix('email:') for r in human};pixels={r['pixel_sha256'] for r in human};seen=set();result=[]
 for row in pseudo:
  if row['id'] in origins or row['pixel_sha256'] in pixels or row['pixel_sha256'] in seen:continue
  if row['label'] not in LABELS:continue
  seen.add(row['pixel_sha256']);result.append(row)
 return result

def score(records):
 lanes={k:dict(tp=0,fp=0,tn=0,fn=0) for k in ('human','hybrid')};groups=set()
 for row in records:
  if not row.get('prospective') or row.get('truth') not in LABELS:continue
  groups.add(row['generation'])
  for lane in lanes:
   predicted=row[lane];truth=row['truth'];lanes[lane][('t' if predicted==truth else 'f')+('p' if predicted=='anomalous' else 'n')]+=1
 for values in lanes.values():
  values['false_positive_rate']=values['fp']/(values['fp']+values['tn']) if values['fp']+values['tn'] else None
  values['recall']=values['tp']/(values['tp']+values['fn']) if values['tp']+values['fn'] else None
 return dict(lanes=lanes,recordings=len(groups),automatic_switch=False,scope='Prospective reviewed detections; not all camera frames or an unbiased event census')
