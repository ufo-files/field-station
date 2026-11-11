"""Paired, prospective daily model comparison; only later human reviews count."""
import json,shlex,subprocess,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from policy import score,LABELS

def timeline(records):
 groups={}
 for row in records:
  if not row.get('prospective') or row.get('truth') not in LABELS:continue
  if row.get('human') not in LABELS or row.get('hybrid') not in LABELS:continue
  if row.get('human_version')==row.get('hybrid_version'):continue
  epoch=row.get('captured_epoch')
  if not isinstance(epoch,(int,float)) or epoch<=0:continue
  day=datetime.fromtimestamp(epoch,ZoneInfo('America/Los_Angeles')).date().isoformat()
  key=(day,row['human_version'],row['hybrid_version'])
  groups.setdefault(key,[]).append(row)
 points=[]
 for (day,human,hybrid),rows in sorted(groups.items()):
  result=score(rows)
  for values in result['lanes'].values():
   total=sum(values[k] for k in ('tp','tn','fp','fn'))
   values['accuracy']=(values['tp']+values['tn'])/total if total else None
  points.append(dict(day=day,human_version=human,hybrid_version=hybrid,count=len(rows),**result))
 return dict(points=points,updated_epoch=time.time(),timezone='America/Los_Angeles')

def publish(root,helper):
 records=json.loads((root/'comparisons.json').read_text()) if (root/'comparisons.json').exists() else {}
 value=timeline(records.values())
 state=json.loads((root/'status.json').read_text())
 value['seed_only']=state.get('shadow_seed_only',True)
 value['phase']=state.get('phase','starting')
 value['error']=state.get('error')
 value['reason']=state.get('reason')
 benchmark=root.parent/'model-comparisons/history.json'
 if benchmark.exists():value=json.loads(benchmark.read_text())
 path=root/'comparison-history.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(path)
 code="from pathlib import Path; p=Path('/Volumes/UFO-Field/uap-lab/model-comparison.json'); t=p.with_suffix('.tmp'); t.write_text("+repr(json.dumps(value))+"); t.replace(p)"
 subprocess.run(['/usr/bin/python3',str(helper),shlex.join(['/Users/ufo-field/ufo-field/venv/bin/python','-c',code])],capture_output=True,check=True,timeout=60)
 return value
