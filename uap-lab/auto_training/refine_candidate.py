"""Learn calibrated class corrections while preserving other incumbent outputs."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

def select_cutoff(rows,results,baseline,label='cloud'):
 options=[]
 for cutoff in [.8,.85,.9,.93,.95,.97,.99,.995,.999]:
  accepted=[(r,b) for r,p,b in zip(rows,results,baseline) if max(p['scores'],key=p['scores'].get)==label and p['scores'][label]>=cutoff and max(r['native_width'],r['native_height'])>=8]
  correct=[r for r,b in accepted if r['label']==label];groups=len({r['group'] for r in correct})
  changed=[r for r,b in accepted if b['label']!=label]
  false=sum(r['label']!=label for r in changed)
  # Evidence that remains correct is still calibration evidence. Requiring NEW
  # corrections here locks training once the incumbent solves this fixed split.
  if false==0 and len(correct)>=2 and groups>=2:options.append((len(correct),cutoff,groups,sum(r['label']==label for r in changed)))
 if not options:return None
 # Corrections override an already deployed classifier. Prefer the strictest
 # independently supported cutoff, rather than maximizing calibration recall.
 count,cutoff,groups,improved=max(options,key=lambda option:(option[1],option[0]))
 return dict(label=label,cutoff=cutoff,correct_calibration_examples=count,corrected_calibration_clouds=improved if label=='cloud' else 0,corrected_calibration_examples=improved,independent_groups=groups,false_overrides=0)

def select_corrections(rows,results,baseline,classes):
 """Do not change an incumbent for a correction with no calibration benefit."""
 return [selection for label in classes if (selection:=select_cutoff(rows,results,baseline,label)) is not None and selection['corrected_calibration_examples']>0]

def refine(folder,baseline):
 import io,os
 os.environ['OMP_NUM_THREADS']='2'
 import torch,numpy as np,coremltools as ct
 from PIL import Image
 from torchvision.models import mobilenet_v3_small
 from torchvision.transforms.functional import to_tensor
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
 from crop_client import CropClassifier
 from training_policy import evaluate
 torch.set_num_threads(2)
 folder,baseline=Path(folder),Path(baseline);dataset=json.loads((folder/'dataset.json').read_text());policy=json.loads((baseline/'candidate-policy.json').read_text());classes=dataset['classes'];tools=folder.parent.parent/'tools'
 if not set(policy['classes'])<=set(classes):raise ValueError('Candidate removed incumbent classes')
 base_classes=policy.get('base_head_classes',policy['classes'])
 if (folder/'refinement.json').exists():return
 proposed=folder/'proposed.mlpackage'
 if not proposed.exists():(folder/'candidate.mlpackage').rename(proposed)
 if not (folder/'proposed-weights.pt').exists():(folder/'candidate-weights.pt').rename(folder/'proposed-weights.pt')
 source=Path(__file__).resolve().parents[1]/'recognition'
 for name in ('compile_model','crop_worker'):
  if not (tools/name).exists():subprocess.run(['swiftc',str(source/(name+'.swift')),'-o',str(tools/name)],check=True,timeout=180)
 rows=[r for r in dataset['samples'] if r['split']=='calibration'];images=[(folder/r['image']).read_bytes() for r in rows]
 def predict(package,identity):
  compiled=tools/(identity+'.mlmodelc')
  if not compiled.exists():subprocess.run([str(tools/'compile_model'),str(package),str(compiled)],check=True,capture_output=True,timeout=300)
  with CropClassifier(tools/'crop_worker',compiled,identity,timeout=120) as worker:results=worker.predict(images)
  if any(r.get('error') for r in results):raise ValueError('Native calibration inference failed')
  return results
 old=predict(baseline/'candidate.mlpackage',policy['version']);new=predict(proposed,dataset['fingerprint']+'-proposed')
 old_metrics=evaluate(rows,[[r['scores'].get(c,0) for c in classes] for r in old],classes,policy['thresholds'])
 selections=select_corrections(rows,new,old_metrics['predictions'],classes)
 selection=dict(classes=selections)
 if not selections:
  (folder/'refinement-decision.json').write_text(json.dumps(dict(state='waiting_for_data',reason='No class correction passed independent calibration without false overrides')))
  raise ValueError('No class correction passed independent calibration without false overrides')
 # The fixed feature extractor must be identical to the incumbent before sharing it.
 prior=torch.load(baseline/'candidate-weights.pt',map_location='cpu',weights_only=True);trained=torch.load(folder/'proposed-weights.pt',map_location='cpu',weights_only=True)
 for name,value in prior.items():
  if name.startswith('features.') and not torch.equal(value,trained[name]):raise ValueError('Incumbent feature extractor differs from the correction model')
 class Features(torch.nn.Module):
  def __init__(self):
   super().__init__();base=mobilenet_v3_small();self.features=base.features;self.pool=base.avgpool;self.prehead=torch.nn.Sequential(*list(base.classifier.children())[:2]);self.register_buffer('mean',torch.tensor([.485,.456,.406]).reshape(1,3,1,1));self.register_buffer('std',torch.tensor([.229,.224,.225]).reshape(1,3,1,1));self.register_buffer('gray',torch.tensor([.299,.587,.114]).reshape(1,3,1,1))
  def forward(self,image):
   gray=(image*self.gray).sum(dim=1,keepdim=True).repeat(1,3,1,1);return self.prehead(torch.flatten(self.pool(self.features((gray-self.mean)/self.std)),1))
 stages=list(policy.get('class_corrections',policy.get('cloud_corrections',[])))
 class Model(torch.nn.Module):
  def __init__(self):
   super().__init__();self.features=Features();self.head=torch.nn.Linear(1024,len(base_classes));self.corrections=torch.nn.ModuleList([torch.nn.Linear(1024,len(stage.get('classes',policy['classes']))) for stage in stages])
  def forward(self,image):
   features=self.features(image);base_scores=torch.softmax(self.head(features),dim=1)
   scores=torch.cat([base_scores[:,base_classes.index(c):base_classes.index(c)+1] if c in base_classes else torch.zeros_like(base_scores[:,:1]) for c in classes],dim=1)
   for head,stage in zip(self.corrections,stages):
    label=stage.get('label','cloud');index=classes.index(label);head_index=stage.get('classes',policy['classes']).index(label);proposal=torch.softmax(head(features),dim=1);accept=(proposal.argmax(dim=1)==head_index)&(proposal[:,head_index]>=stage['cutoff']);decision=torch.zeros_like(scores);decision[:,index]=1.;scores=torch.where(accept[:,None],decision,scores)
   return scores
 model=Model().eval();model.load_state_dict(prior,strict=True)
 for stage in stages:stage.setdefault('classes',policy['classes'])
 for selected in selections:
  correction=torch.nn.Linear(1024,len(classes));correction.load_state_dict({'weight':trained['head.weight'],'bias':trained['head.bias']});model.corrections.append(correction);stages.append(dict(selected,classes=classes,review_fingerprint=dataset['review_fingerprint']))
 traced=torch.jit.trace(model,torch.rand(1,3,224,224),check_trace=False)
 exported=ct.convert(traced,inputs=[ct.ImageType(name='image',shape=(1,3,224,224),scale=1/255)],classifier_config=ct.ClassifierConfig(classes),minimum_deployment_target=ct.target.macOS13,compute_precision=ct.precision.FLOAT32)
 exported.save(str(folder/'candidate.mlpackage'));torch.save(model.state_dict(),folder/'candidate-weights.pt')
 errors=[]
 for row in rows[:10]:
  with Image.open(folder/row['image']) as source:im=source.convert('RGB').resize((224,224),Image.Resampling.BILINEAR)
  with torch.no_grad():expected=model(to_tensor(im)[None]).numpy()[0]
  actual=next(v for v in exported.predict({'image':im}).values() if isinstance(v,dict));errors.append(max(abs(float(expected[i])-actual[label]) for i,label in enumerate(classes)))
 error=max(errors)
 if error>.025:raise ValueError('Focused correction export parity failed')
 thresholds={c:policy['thresholds'].get(c,1.1) for c in classes}
 for selected in selections:
  if thresholds[selected['label']]>1:thresholds[selected['label']]=.8
 deferred=[c for c in classes if thresholds[c]>1]
 report=json.loads((folder/'evaluation.json').read_text());report.update(export_max_absolute_error=error,thresholds=thresholds,correction_calibration=selection)
 (folder/'evaluation.json').write_text(json.dumps(report));(folder/'candidate-policy.json').write_text(json.dumps(dict(policy,version=dataset['fingerprint'],classes=classes,base_head_classes=base_classes,thresholds=thresholds,deferred_classes=deferred,focused_cloud_correction=True,class_corrections=stages,parent_version=policy['version'],score_semantics='Decision scores; 1 means a calibrated class correction was accepted, not certainty')))
 (folder/'refinement.json').write_text(json.dumps(dict(selection,baseline_version=policy['version'],export_max_absolute_error=error)))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--baseline',required=True);a=p.parse_args();refine(a.folder,a.baseline)
