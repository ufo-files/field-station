"""Frozen, offline comparisons. Never activates a model or edits historical runs."""
import argparse,collections,hashlib,json,math,random,subprocess,sys,time
from pathlib import Path
from correction_experiment import select_rules,apply_rules
from training_policy import summarize,calibrate_against_incumbent,evaluate
from evaluate_candidate import gate
CLASSES=['anomalous','not_anomalous']

def compact(report):
 p=report['predictions'];n=len(p);correct=sum(r['label']==r['truth'] for r in p);unknown=sum(r['label']=='unknown' for r in p)
 return dict(total=n,correct=correct,wrong=n-correct-unknown,unknown=unknown,accuracy=correct/n if n else None,coverage=(n-unknown)/n if n else None,accepted_accuracy=correct/(n-unknown) if n>unknown else None,raw_accuracy=sum(r['raw_label']==r['truth'] for r in p)/n if n else None,per_class=report['per_class'])

def native_calibration(folder,dataset,root):
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
 from crop_client import CropClassifier
 policy=json.loads((folder/'candidate-policy.json').read_text());tools=root/'tools';compiled=tools/(policy['version']+'.mlmodelc')
 if not compiled.exists():subprocess.run([str(tools/'compile_model'),str(folder/'candidate.mlpackage'),str(compiled)],check=True,capture_output=True,timeout=300)
 rows=[r for r in dataset['samples'] if r['split']=='calibration']
 with CropClassifier(tools/'crop_worker',compiled,policy['version'],timeout=120) as worker:results=worker.predict([(folder/r['image']).read_bytes() for r in rows])
 if any(r.get('error') for r in results):raise ValueError('Calibration inference failed')
 return evaluate(rows,[[r['scores'][c] for c in CLASSES] for r in results],CLASSES,policy['thresholds'])

def stability(baseline,proposed,repeats=200):
 groups=sorted({p['group'] for p in proposed});old={p['origin']:p for p in baseline};by_group=collections.defaultdict(list)
 for p in proposed:by_group[p['group']].append(p)
 rng=random.Random(731);counts=collections.Counter();cutoffs=collections.defaultdict(list)
 for _ in range(repeats):
  b=[];p=[]
  for i,g in enumerate(rng.choices(groups,k=len(groups))):
   for row in by_group[g]:
    origin=row['origin']+':bootstrap:'+str(i);b.append(dict(old[row['origin']],origin=origin));p.append(dict(row,origin=origin))
  for rule in select_rules(b,p):counts[rule['label']]+=1;cutoffs[rule['label']].append(rule['cutoff'])
 return {c:dict(selected_fraction=counts[c]/repeats,cutoff_counts=dict(collections.Counter(cutoffs[c]))) for c in CLASSES}

def calibrate_sigmoid(calibration,testing):
 """Group-disjoint out-of-fold sigmoid calibration; test labels never fit anything."""
 import numpy as np
 from sklearn.model_selection import StratifiedGroupKFold
 from sklearn.linear_model import LogisticRegression
 def arrays(rows):
  probability=np.asarray([p['score'] if p['raw_label']=='anomalous' else 1-p['score'] for p in rows]);probability=np.clip(probability,1e-6,1-1e-6)
  return np.log(probability/(1-probability)).reshape(-1,1),np.asarray([p['truth']=='anomalous' for p in rows],dtype=int)
 x,y=arrays(calibration);groups=np.asarray([r['group'] for r in calibration]);oof=np.zeros(len(y));folds=StratifiedGroupKFold(n_splits=5,shuffle=True,random_state=731)
 for train,valid in folds.split(x,y,groups):
  if set(groups[train])&set(groups[valid]):raise ValueError('Calibration group leakage')
  if len(set(y[train]))<2:raise ValueError('Calibration fold lacks both classes')
  model=LogisticRegression(C=1,max_iter=2000,random_state=731).fit(x[train],y[train]);oof[valid]=model.predict_proba(x[valid])[:,1]
 model=LogisticRegression(C=1,max_iter=2000,random_state=731).fit(x,y);test_x,_=arrays(testing);test_p=model.predict_proba(test_x)[:,1]
 def predictions(rows,probabilities):
  return [dict(r,raw_label='anomalous' if p>=.5 else 'not_anomalous',score=float(max(p,1-p))) for r,p in zip(rows,probabilities)]
 original=np.asarray([r['score'] if r['raw_label']=='anomalous' else 1-r['score'] for r in calibration])
 return predictions(calibration,oof),predictions(testing,test_p),dict(method='group-disjoint five-fold sigmoid; final sigmoid fitted on calibration only',original_calibration_brier=float(np.mean((original-y)**2)),out_of_fold_calibration_brier=float(np.mean((oof-y)**2)),coefficient=float(model.coef_[0,0]),intercept=float(model.intercept_[0]))

def compare(source,balanced,root,out):
 source,balanced,root,out=map(Path,(source,balanced,root,out));d=json.loads((source/'dataset.json').read_text());bd=json.loads((balanced/'dataset.json').read_text())
 identity=lambda rows:hashlib.sha256(json.dumps(sorted((r['origin'],r['label'],r['pixel_sha256'],r['group'],r['split']) for r in rows)).encode()).hexdigest()
 if identity(d['samples'])!=identity(bd['samples']):raise ValueError('Experimental evidence differs')
 rows={r['origin']:r for r in d['samples']};base=json.loads((source/'promotion-evaluation.json').read_text());weighted=json.loads((balanced/'promotion-evaluation.json').read_text());baseline=base['baseline'];base_cal=base['baseline_calibration'];results={};details={}
 def annotate(report):
  return [dict(p,native_eligible=max(rows[p['origin']]['native_width'],rows[p['origin']]['native_height'])>=8) for p in report['predictions']]
 def add(name,report,policy=None):
  # Offline replay is not a Core ML export or permission to activate a model.
  decision=gate(dict(report,export_max_absolute_error=report.get('export_max_absolute_error',0),thresholds=report.get('thresholds',{'anomalous':.8})),baseline,CLASSES,CLASSES)
  results[name]=dict(**compact(report),regression_gate=decision,production_qualified=False,policy=policy)
  details[name]=report
 add('incumbent',baseline);add('current_binary',base['candidate']);add('recording_balanced',weighted['candidate'])
 for name,report,folder in [('current',base,source),('balanced',weighted,balanced)]:
  cal=report.get('candidate_calibration') or native_calibration(folder,d,root)
  proposed=annotate(cal);test=annotate(report['candidate']);old=annotate(base_cal)
  rules=select_rules(old,proposed)
  corrected=summarize(apply_rules(baseline['predictions'],test,rules),CLASSES)
  add(name+'_incumbent_corrections',corrected,dict(rules=rules,calibration_stability=stability(old,proposed)))
  calibrated,calibrated_test,evidence=calibrate_sigmoid(proposed,test)
  probability=lambda rs:[[p['score'],1-p['score']] if p['raw_label']=='anomalous' else [1-p['score'],p['score']] for p in rs]
  cal_rows=[dict(rows[p['origin']],label=p['truth']) for p in calibrated]
  thresholds,ev=calibrate_against_incumbent(cal_rows,probability(calibrated),CLASSES,base_cal)
  test_rows=[dict(rows[p['origin']],label=p['truth']) for p in calibrated_test]
  result=evaluate(test_rows,probability(calibrated_test),CLASSES,thresholds)
  add(name+'_sigmoid',result,dict(**evidence,thresholds=thresholds,threshold_evidence=ev))
  details[name+'_calibration']=cal
  # Diagnostic rules are selected above using calibration; never sweep test cutoffs.
 current=[r for r in d['samples'] if r.get('human_confirmed')];groups=collections.Counter(r['group'] for r in current)
 report=dict(schema=1,created_epoch=time.time(),source_run=str(source),balanced_run=str(balanced),evidence_identity=identity(d['samples']),test_identity=identity([r for r in d['samples'] if r['split']=='test']),human_examples=len(current),human_groups=len(groups),largest_three_group_share=sum(v for _,v in groups.most_common(3))/len(current),results=results,limitations=['Frozen historical regression benchmark; no prospective accuracy claim','Correction strategies are offline decision replay, not production-qualified exports','Sigmoid experiment uses recording-disjoint calibration folds; test data never chooses thresholds','Raw accuracy for correction replay retains incumbent raw predictions; compare accepted decisions and coverage'])
 out.mkdir(parents=True,exist_ok=True);(out/'comparison.json').write_text(json.dumps(report,indent=2));(out/'prediction-details.json').write_text(json.dumps(details));print(json.dumps(report,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--balanced',required=True);p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();compare(a.source,a.balanced,a.root,a.out)
