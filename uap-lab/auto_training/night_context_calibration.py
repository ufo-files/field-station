"""Qualify the fixed conservative context rule for each new model on current reviewed pairs."""
import hashlib,io,json,tarfile,math
from pathlib import Path
from PIL import Image
FLOOR=.001

def counts(rows,tight,context,threshold,floor=FLOOR):
 before=dict(tp=0,fp=0,tn=0,fn=0);after=dict(before)
 for row,a,b in zip(rows,tight,context):
  if not all(math.isfinite(v) and 0<=v<=1 for v in (a,b)):raise ValueError('Invalid context evaluation score')
  positive=a>=threshold
  for target,prediction in [(before,positive),(after,positive and b>=floor)]:
   truth=row['label']=='anomalous';target[('t' if prediction==truth else 'f')+('p' if prediction else 'n')]+=1
 if len(rows)!=len(tight) or len(rows)!=len(context):raise ValueError('Incomplete context evaluation')
 return before,after

def qualify(folder,dataset,worker,threshold):
 archive=folder.parent.parent/'crop-parity-audit.tar';version=dataset['fingerprint']
 rule=dict(enabled=False,version=version,minimum_context_score=FLOOR,geometry='review-context-v1')
 if not archive.exists():return rule
 latest={r['origin']:r for r in dataset['samples'] if r.get('human_confirmed')};rows=[];images={'tight':[],'context':[]}
 with tarfile.open(archive) as tar:
  source=json.load(tar.extractfile('samples.json'))
  for row in source:
   current=latest.get('email:'+row['id'])
   if not current:continue
   raw=tar.extractfile(row['id']+'-context.png').read()
   im=Image.open(io.BytesIO(raw)).convert('RGB');w,h=im.size
   if hashlib.sha256(f'{w}x{h}:RGB:'.encode()+im.tobytes()).hexdigest()!=current['pixel_sha256']:continue
   rows.append(dict(row,label=current['label']));images['context'].append(raw);images['tight'].append(tar.extractfile(row['id']+'-tight.png').read())
 scores={}
 for kind,values in images.items():
  values_out=[]
  for start in range(0,len(values),64):values_out.extend(worker.predict(values[start:start+64]))
  if any(r.get('error') for r in values_out):raise ValueError('Context qualification inference failed')
  scores[kind]=[r['scores']['anomalous'] for r in values_out]
 before,after=counts(rows,scores['tight'],scores['context'],threshold)
 groups={label:len({r['generation'] for r in rows if r['label']==label}) for label in ('anomalous','not_anomalous')}
 rule.update(enabled=before['tp']>=20 and before['fp']>=20 and after['tp']==before['tp'] and after['fp']<=.8*before['fp'] and min(groups.values())>=2)
 report=dict(rule=rule,before=before,after=after,groups=groups,samples=len(rows),limitations=['Reviewed training examples, not an independent generalization test.','Rule only rejects tight-crop alerts whose contextual anomaly score is below 0.001.','Daytime and all retained training labels are unchanged.'])
 (folder/'night-context-qualification.json').write_text(json.dumps(report));return rule
