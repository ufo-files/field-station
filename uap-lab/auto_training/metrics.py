"""Publish held-out evaluation history, including manual training attempts."""
import hashlib,json,time
from pathlib import Path

def build(root):
 points=[]
 for path in sorted((Path(root)/'runs').glob('*/promotion-evaluation.json')):
  report=json.loads(path.read_text());candidate=report.get('candidate',{});baseline=report.get('baseline',{})
  predictions=candidate.get('predictions',[])
  # Changing validation membership must not look like a continuous improvement.
  cohort=hashlib.sha256(json.dumps(sorted((r['origin'],r['truth'],r.get('group')) for r in predictions)).encode()).hexdigest() if predictions else None
  def metric(value):
   total=value.get('total',0);correct=sum(v.get('tp',0) for v in value.get('per_class',{}).values())
   return dict(total=total,correct=correct,accuracy=correct/total if total else None,unknown=value.get('unknown',0),per_class=value.get('per_class',{}))
  points.append(dict(epoch=report['epoch'],version=report['candidate_version'],baseline_version=report['baseline_version'],passed=report['passed'],reasons=report.get('reasons',[]),cohort=cohort,candidate=metric(candidate),baseline=metric(baseline)))
 return dict(updated_epoch=time.time(),points=sorted(points,key=lambda p:p['epoch']))

def publish(controller):
 payload=json.dumps(build(controller.root)).encode()
 script='import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(".tmp"); t.write_bytes(sys.stdin.buffer.read()); t.replace(p)'
 controller.remote([controller.python,'-c',script,controller.app+'/auto-training/metrics.json'],input=payload,capture_output=True,timeout=30)
