"""Publish held-out evaluation history, including manual training attempts."""
import hashlib,json,time
from pathlib import Path
from training_policy import project_binary

def build(root):
 points=[]
 root=Path(root)
 for path in sorted((Path(root)/'runs').glob('*/promotion-evaluation.json')):
  report=json.loads(path.read_text());candidate=report.get('candidate',{});baseline=report.get('baseline',{})
  original_candidate=candidate;original_baseline=baseline
  projected=all(v.get('predictions') and all('label' in p and 'raw_label' in p for p in v['predictions']) for v in (candidate,baseline))
  if projected:candidate=project_binary(candidate);baseline=project_binary(baseline)
  predictions=candidate.get('predictions',[])
  # Changing validation membership must not look like a continuous improvement.
  cohort=hashlib.sha256(json.dumps(sorted((r['origin'],r['truth'],r.get('group')) for r in predictions)).encode()).hexdigest() if predictions else None
  def metric(value):
   total=value.get('total',0);correct=sum(v.get('tp',0) for v in value.get('per_class',{}).values())
   unknown=value.get('unknown',0);predictions=value.get('predictions',[]);accepted=total-unknown
   raw_correct=sum(r.get('raw_label')==r['truth'] for r in predictions)
   return dict(total=total,correct=correct,accuracy=correct/total if total else None,raw_accuracy=raw_correct/len(predictions) if predictions and all('raw_label' in r for r in predictions) else None,accepted_accuracy=correct/accepted if accepted else None,coverage=accepted/total if total else None,unknown=unknown,per_class=value.get('per_class',{}))
  dataset_path=path.parent/'dataset.json'
  dataset=json.loads(dataset_path.read_text()) if dataset_path.exists() else {}
  points.append(dict(run_id=path.parent.name,reviewed_examples=sum(dataset.get('human_training_counts',{}).values()) or None,evaluation_complete=True,taxonomy='binary' if projected else 'legacy',original_candidate=metric(original_candidate),original_baseline=metric(original_baseline),epoch=report['epoch'],version=report['candidate_version'],baseline_version=report['baseline_version'],passed=report['passed'],manual_deployment=report.get('manual_deployment'),reasons=report.get('reasons',[]),improved=report.get('improved'),deferred_classes=report.get('deferred_classes',[]),validation_coverage=report.get('validation_coverage',{}),limitations=report.get('limitations',[]),cohort=cohort,candidate=metric(candidate),baseline=metric(baseline)))
 evaluated={p['run_id'] for p in points}
 # Earlier stops have no promotion report. Keep them in history without inventing scores.
 for folder in sorted((root/'runs').iterdir()) if (root/'runs').exists() else []:
  if not folder.is_dir() or folder.name in evaluated or '.incomplete.' in folder.name:continue
  def read(name):
   try:return json.loads((folder/name).read_text())
   except (OSError,ValueError):return {}
  outcome=read('run-outcome.json');decision=read('refinement-decision.json');dataset=read('dataset.json')
  if not outcome and not decision:continue
  phase=outcome.get('phase',decision.get('state','unknown'))
  reason=outcome.get('reason') or decision.get('reason')
  stamp=outcome.get('updated_epoch') or (folder/'refinement-decision.json').stat().st_mtime
  points.append(dict(run_id=folder.name,epoch=stamp,version=dataset.get('fingerprint',folder.name),baseline_version=outcome.get('active_version'),phase=phase,passed=None,improved=None,evaluation_complete=False,reviewed_examples=sum(dataset.get('human_training_counts',{}).values()) or outcome.get('examples'),reasons=reason if isinstance(reason,list) else [reason] if reason else [],candidate=None,baseline=None,cohort=None,taxonomy='binary' if dataset.get('classes')==['anomalous','not_anomalous'] else 'legacy'))
 return dict(updated_epoch=time.time(),points=sorted(points,key=lambda p:p['epoch']))

def publish(controller):
 payload=json.dumps(build(controller.root)).encode()
 script='import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(".tmp"); t.write_bytes(sys.stdin.buffer.read()); t.replace(p)'
 controller.remote([controller.python,'-c',script,controller.app+'/auto-training/metrics.json'],input=payload,capture_output=True,timeout=30)
