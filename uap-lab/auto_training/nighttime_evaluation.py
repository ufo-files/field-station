"""Supplementary reviewed-night crop replay; never changes deployment or thresholds."""
import argparse,json,random,sys
from collections import defaultdict
from pathlib import Path

def select(rows,metadata,per_class=500):
 pools=defaultdict(lambda:defaultdict(list));seen=set()
 for row in rows:
  if metadata.get(row['origin'],{}).get('period')!='nighttime' or not row.get('human_confirmed'):continue
  if row['label'] not in ('anomalous','not_anomalous'):continue
  identity=(row['label'],row['pixel_sha256'])
  if identity in seen:continue
  seen.add(identity);pools[row['label']][row['group']].append(row)
 rng=random.Random(731);selected=[]
 for label,groups in sorted(pools.items()):
  keys=sorted(groups);rng.shuffle(keys)
  for values in groups.values():rng.shuffle(values)
  count=0
  while keys and count<per_class:
   for key in list(keys):
    selected.append(groups[key].pop());count+=1
    if not groups[key]:keys.remove(key)
    if count>=per_class:break
 return selected

def summarize(rows,scores,threshold):
 from binary_decision import decide
 counts=dict(tp=0,fp=0,tn=0,fn=0)
 for row,score in zip(rows,scores):
  predicted=decide(score,threshold);truth=row['label']
  counts[('t' if truth==predicted else 'f')+('p' if predicted=='anomalous' else 'n')]+=1
 if len(rows)!=len(scores):raise ValueError('Missing predictions')
 return dict(counts,threshold=threshold,false_positive_rate=counts['fp']/(counts['fp']+counts['tn']) if counts['fp']+counts['tn'] else None,positive_recall=counts['tp']/(counts['tp']+counts['fn']) if counts['tp']+counts['fn'] else None)

def evaluate(folder,metadata,baseline):
 import subprocess
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
 from crop_client import CropClassifier
 dataset=json.loads((folder/'dataset.json').read_text());rows=select(dataset['samples'],metadata)
 tools=folder.parent.parent/'tools'
 result=dict(kind='reviewed_nighttime_replay',limitations=['Reviewed training crops; not an unbiased estimate on unseen recordings.','Balanced by class and recording; does not estimate alert prevalence.','Objects without verified capture times are excluded.'],samples=[{k:r[k] for k in ('origin','label','group','pixel_sha256')} for r in rows],models={})
 if not rows:raise ValueError('No reviewed nighttime samples')
 for name,source in [('previous',baseline),('new',folder)]:
  policy=json.loads((source/'candidate-policy.json').read_text());version=policy['version'];compiled=tools/(version+'.mlmodelc')
  if not compiled.exists():subprocess.run([str(tools/'compile_model'),str(source/'candidate.mlpackage'),str(compiled)],check=True,capture_output=True,timeout=300)
  predictions=[]
  with CropClassifier(tools/'crop_worker',compiled,version,timeout=120) as worker:
   for start in range(0,len(rows),64):
    predictions.extend(worker.predict([(folder/r['image']).read_bytes() for r in rows[start:start+64]]))
  if any(p.get('error') for p in predictions):raise ValueError('Nighttime inference failed')
  scores=[p['scores'] for p in predictions];threshold=policy['thresholds']['anomalous']
  result['models'][name]=dict(version=version,current=summarize(rows,scores,threshold),threshold_sweep=[summarize(rows,scores,t) for t in sorted(set([threshold,.8,.85,.9,.95,.975,.99,.995,.999]))],scores=scores)
 path=folder/'nighttime-evaluation.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result));tmp.replace(path)
 return {name:value['current'] for name,value in result['models'].items()}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True);p.add_argument('--metadata',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);a=p.parse_args();print(json.dumps(evaluate(a.folder,json.loads(a.metadata.read_text()),a.baseline)))
