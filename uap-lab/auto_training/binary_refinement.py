"""Preserve incumbent decisions and append independently calibrated binary corrections."""
import json,subprocess,sys
from pathlib import Path
from correction_experiment import select_rules

def refine_binary(folder,baseline):
 import torch,coremltools as ct
 from torchvision.models import mobilenet_v3_small
 from torchvision.transforms.functional import to_tensor
 from PIL import Image
 from training_policy import evaluate,project_binary
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
 from crop_client import CropClassifier
 from classification_taxonomy import canonical_label
 folder,baseline=Path(folder),Path(baseline);dataset=json.loads((folder/'dataset.json').read_text());policy=json.loads((baseline/'candidate-policy.json').read_text());classes=dataset['classes'];tools=folder.parent.parent/'tools'
 proposed_policy=json.loads((folder/'candidate-policy.json').read_text())
 if policy.get('input_color_space','GRAY')!=proposed_policy.get('input_color_space','GRAY'):raise ValueError('Color-space changes require a full model; correction heads cannot mix RGB and grayscale features')
 if (folder/'refinement.json').exists():return
 torch.set_num_threads(2)
 rows=[r for r in dataset['samples'] if r['split']=='calibration'];images=[(folder/r['image']).read_bytes() for r in rows]
 def predict(package,version,labels):
  compiled=tools/(version+'.mlmodelc')
  if not compiled.exists():subprocess.run([str(tools/'compile_model'),str(package),str(compiled)],check=True,capture_output=True,timeout=300)
  with CropClassifier(tools/'crop_worker',compiled,version,timeout=120) as worker:results=worker.predict(images)
  if any(r.get('error') for r in results):raise ValueError('Native correction calibration failed')
  return evaluate(rows,[[r['scores'].get(c,0) for c in labels] for r in results],labels,policy['thresholds'] if labels==policy['classes'] else {c:.8 for c in labels})
 # Evaluate with the incumbent's labels and thresholds, then project its decisions.
 old=predict(baseline/'candidate.mlpackage',policy['version'],policy['classes'])
 if set(policy['classes'])!=set(classes):old=project_binary(old)
 proposed=folder/'proposed.mlpackage'
 if not proposed.exists():(folder/'candidate.mlpackage').rename(proposed)
 weights=folder/'proposed-weights.pt'
 if not weights.exists():(folder/'candidate-weights.pt').rename(weights)
 new=predict(proposed,dataset['fingerprint']+'-proposed',classes)
 for p,r in zip(new['predictions'],rows):p['native_eligible']=max(r['native_width'],r['native_height'])>=8
 rules=select_rules(old['predictions'],new['predictions'])
 if not rules:
  (folder/'refinement-decision.json').write_text(json.dumps(dict(state='not_promoted',reason='No binary correction had five calibration improvements across three recordings without false overrides')))
  raise ValueError('No independently supported binary correction')
 prior=torch.load(baseline/'candidate-weights.pt',map_location='cpu',weights_only=True);trained=torch.load(weights,map_location='cpu',weights_only=True)
 for name,value in prior.items():
  if name.startswith('features.') and not torch.equal(value,trained[name]):raise ValueError('Feature extractor differs from incumbent')
 legacy=policy.get('legacy_classes',policy['classes']);base_classes=policy.get('base_head_classes',legacy);legacy_thresholds=policy.get('legacy_thresholds',policy['thresholds']);stages=policy.get('class_corrections',policy.get('cloud_corrections',[]));binary_stages=list(policy.get('binary_corrections',[]))
 from vision_features import build_features
 class Model(torch.nn.Module):
  def __init__(self):
   super().__init__();self.features=build_features(mobilenet_v3_small(),grayscale=policy.get('input_color_space','GRAY')!='RGB');self.head=torch.nn.Linear(1024,len(base_classes));self.corrections=torch.nn.ModuleList([torch.nn.Linear(1024,len(s.get('classes',legacy))) for s in stages]);self.binary_corrections=torch.nn.ModuleList([torch.nn.Linear(1024,len(classes)) for _ in binary_stages])
  def forward(self,image):
   features=self.features(image);raw=torch.softmax(self.head(features),dim=1)
   scores=torch.cat([raw[:,base_classes.index(c):base_classes.index(c)+1] if c in base_classes else torch.zeros_like(raw[:,:1]) for c in legacy],dim=1)
   for head,stage in zip(self.corrections,stages):
    label=stage.get('label','cloud');index=legacy.index(label);head_index=stage.get('classes',legacy).index(label);proposal=torch.softmax(head(features),dim=1);accept=(proposal.argmax(dim=1)==head_index)&(proposal[:,head_index]>=stage['cutoff']);decision=torch.zeros_like(scores);decision[:,index]=1.;scores=torch.where(accept[:,None],decision,scores)
   winner=scores.argmax(dim=1);binary=torch.zeros_like(scores[:,:2])
   for i,label in enumerate(legacy):
    mapped=canonical_label(label)
    if mapped not in classes:continue
    value=torch.where(scores[:,i]>=legacy_thresholds.get(label,1.1),torch.ones_like(scores[:,i]),torch.full_like(scores[:,i],.5))
    binary[:,classes.index(mapped)]+=torch.where(winner==i,value,torch.zeros_like(value))
   for head,stage in zip(self.binary_corrections,binary_stages):
    i=classes.index(stage['label']);p=torch.softmax(head(features),dim=1);accept=(p.argmax(dim=1)==i)&(p[:,i]>=stage['cutoff']);decision=torch.zeros_like(binary);decision[:,i]=1.;binary=torch.where(accept[:,None],decision,binary)
   return binary
 model=Model().eval();model.load_state_dict(prior,strict=True)
 for rule in rules:
  head=torch.nn.Linear(1024,len(classes));head.load_state_dict({'weight':trained['head.weight'],'bias':trained['head.bias']});model.binary_corrections.append(head);binary_stages.append(dict(rule,review_fingerprint=dataset['review_fingerprint']))
 traced=torch.jit.trace(model,torch.rand(1,3,224,224),check_trace=False)
 exported=ct.convert(traced,inputs=[ct.ImageType(name='image',shape=(1,3,224,224),scale=1/255)],classifier_config=ct.ClassifierConfig(classes),minimum_deployment_target=ct.target.macOS13,compute_precision=ct.precision.FLOAT32)
 exported.save(str(folder/'candidate.mlpackage'));torch.save(model.state_dict(),folder/'candidate-weights.pt')
 errors=[]
 for row in rows[:10]:
  with Image.open(folder/row['image']) as im:im=im.convert('RGB').resize((224,224),Image.Resampling.BILINEAR)
  with torch.no_grad():expected=model(to_tensor(im)[None]).numpy()[0]
  actual=next(v for v in exported.predict({'image':im}).values() if isinstance(v,dict));errors.append(max(abs(float(expected[i])-actual[label]) for i,label in enumerate(classes)))
 error=max(errors)
 if error>.025:raise ValueError('Binary correction export parity failed')
 thresholds={c:.8 for c in classes};report=json.loads((folder/'evaluation.json').read_text());report.update(export_max_absolute_error=error,thresholds=thresholds,correction_calibration=dict(rules=rules))
 (folder/'evaluation.json').write_text(json.dumps(report));(folder/'candidate-policy.json').write_text(json.dumps(dict(policy,version=dataset['fingerprint'],classes=classes,thresholds=thresholds,legacy_classes=legacy,legacy_thresholds=legacy_thresholds,base_head_classes=base_classes,binary_corrections=binary_stages,focused_cloud_correction=True,parent_version=policy['version'],score_semantics='Decision scores: 1 is an accepted decision; 0.5 preserves an abstention. Neither is a calibrated probability.')))
 (folder/'refinement.json').write_text(json.dumps(dict(rules=rules,baseline_version=policy['version'],export_max_absolute_error=error,method='incumbent_preserving_binary_corrections')))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--baseline',required=True);a=p.parse_args();refine_binary(a.folder,a.baseline)
