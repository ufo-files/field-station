"""Compare candidate and incumbent on exactly the same held-out recordings."""
import argparse,json,time
from pathlib import Path

def gate(candidate,baseline,classes,baseline_classes,blockers=()):
 reasons=list(blockers)
 if not set(baseline_classes)<=set(classes):reasons.append('Candidate removed an active class')
 if candidate.get('export_max_absolute_error',1)>.025:reasons.append('Core ML export parity failed')
 if candidate['total']!=baseline['total'] or not candidate['total']:reasons.append('Held-out sample count mismatch')
 for label in baseline_classes:
  c=candidate['per_class'].get(label,{});b=baseline['per_class'].get(label,{})
  if c.get('tp',0)<b.get('tp',0):reasons.append(label+': held-out recall regressed')
  if c.get('fp',0)>b.get('fp',0):reasons.append(label+': held-out false positives increased')
 if candidate.get('thresholds',{}).get('anomalous',1.1)>1:reasons.append('Anomaly detection disabled by calibration')
 if candidate.get('cloud_false_suppression',0)>baseline.get('cloud_false_suppression',0):reasons.append('Cloud false suppression increased')
 for label in set(classes)-set(baseline_classes):
  c=candidate['per_class'].get(label,{})
  if c.get('precision') is None or c['precision']<.9 or c.get('recall',0)<.5:reasons.append(label+': new class lacks held-out performance')
 return dict(passed=not reasons,reasons=reasons)

def evaluate(folder,baseline_package,baseline_policy):
 import subprocess,sys,math
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
 from crop_client import CropClassifier
 from training_policy import evaluate as metrics,calibrate_against_incumbent
 folder=Path(folder);dataset=json.loads((folder/'dataset.json').read_text());candidate=json.loads((folder/'evaluation.json').read_text());policy=json.loads(Path(baseline_policy).read_text());testing=[r for r in dataset['samples'] if r['split']=='test'];calibration=[r for r in dataset['samples'] if r['split']=='calibration'];reviews=[r for r in dataset['samples'] if r['origin'].startswith(('email:','lab:'))];selected=calibration+testing+reviews
 tools=folder.parent.parent/'tools';tools.mkdir(exist_ok=True);source=Path(__file__).resolve().parents[1]/'recognition'
 for name in ('compile_model','crop_worker'):
  if not (tools/name).exists():subprocess.run(['swiftc',str(source/(name+'.swift')),'-o',str(tools/name)],check=True,timeout=180)
 def predict(package,version,classes):
  compiled=tools/(version+'.mlmodelc')
  if not compiled.exists():subprocess.run([str(tools/'compile_model'),str(package),str(compiled)],check=True,timeout=300,capture_output=True)
  with CropClassifier(tools/'crop_worker',compiled,version,timeout=120) as worker:
   results=worker.predict([(folder/r['image']).read_bytes() for r in selected])
  if any(r.get('error') for r in results):raise ValueError('Runtime classifier failed held-out evaluation')
  probabilities=[[float(r['scores'].get(c,0)) for c in classes] for r in results]
  if any(not math.isfinite(v) for row in probabilities for v in row):raise ValueError('Invalid runtime probability')
  return probabilities,results
 base_p,base_results=predict(baseline_package,policy['version'],policy['classes'])
 candidate_p,candidate_results=predict(folder/'candidate.mlpackage',dataset['fingerprint'],dataset['classes'])
 n=len(calibration);m=len(testing)
 base_cal=metrics(calibration,base_p[:n],policy['classes'],policy['thresholds'])
 thresholds,evidence=calibrate_against_incumbent(calibration,candidate_p[:n],dataset['classes'],base_cal)
 candidate_policy=json.loads((folder/'candidate-policy.json').read_text())
 if candidate_policy.get('focused_cloud_correction'):thresholds=policy['thresholds'];evidence=candidate.get('correction_calibration',{})
 candidate.update(thresholds=thresholds,calibration=evidence,calibration_runtime='Vision/CoreML',calibration_policy='incumbent-per-class-false-positive-budget')
 candidate_policy=json.loads((folder/'candidate-policy.json').read_text());candidate_policy['thresholds']=thresholds
 (folder/'candidate-policy.json').write_text(json.dumps(candidate_policy))
 baseline=metrics(testing,base_p[n:n+m],policy['classes'],policy['thresholds']);candidate.update(metrics(testing,candidate_p[n:n+m],dataset['classes'],thresholds))
 corrections=dict(note='Training-fit diagnostic only; not held-out generalization evidence',baseline=metrics(reviews,base_p[n+m:],policy['classes'],policy['thresholds']),candidate=metrics(reviews,candidate_p[n+m:],dataset['classes'],thresholds))

 decision=gate(candidate,baseline,dataset['classes'],policy['classes'],dataset['blockers'])
 smoke=[]
 # A bounded, deterministic per-class runtime probe travels with the candidate.
 for label in dataset['classes']:smoke.extend([i for i,r in enumerate(testing) if r['label']==label][:4])
 (folder/'runtime-probe.json').write_text(json.dumps([dict(image=testing[i]['image'],scores=candidate_results[n+i]['scores']) for i in smoke]))
 report=dict(**decision,epoch=time.time(),baseline_version=policy['version'],candidate_version=dataset['fingerprint'],review_fingerprint=dataset['review_fingerprint'],baseline=baseline,candidate=candidate,reviewed_corrections=corrections,baseline_calibration=base_cal,gate='same-held-out-recordings-per-class-nonregression',runtime='Vision/CoreML native crop preprocessing')
 (folder/'promotion-evaluation.json').write_text(json.dumps(report));return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--baseline-package',required=True);p.add_argument('--baseline-policy',required=True);a=p.parse_args();r=evaluate(a.folder,a.baseline_package,a.baseline_policy);print(json.dumps({k:r[k] for k in ('passed','reasons','candidate_version','baseline_version')}))
