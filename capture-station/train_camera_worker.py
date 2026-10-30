#!/usr/bin/env python3
"""Mac-only transfer learning worker. Dataset groups are split before upload."""
import argparse
import base64
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time

ROOT=Path(__file__).resolve().parent


def write(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2));temporary.replace(path)


def emit(folder,phase,**details):
    value=dict(phase=phase,updated_epoch=time.time(),**details);write(folder/'status.json',value)
    print(json.dumps(value),flush=True)


def invoke_vision(images,policy=None):
    payload=dict(images=[base64.b64encode(p.read_bytes()).decode() for p in images])
    if policy:payload['policy_path']=str(policy)
    results=[]
    for offset in range(0,len(images),20):
        batch=dict(payload,images=payload['images'][offset:offset+20])
        r=subprocess.run([str(ROOT/'vision_worker')],input=json.dumps(batch).encode(),capture_output=True,timeout=120)
        if r.returncode:raise OSError('Inference check failed: '+r.stderr.decode(errors='replace')[-400:])
        response=json.loads(r.stdout)
        if response.get('model_error'):raise OSError(response['model_error'])
        if any(v.get('error') for v in response['results']):raise OSError('An evaluation image failed inference')
        results.extend(response['results'])
    return results


def label_category(identifier):
    tokens=set(re.split('[^a-z]+',identifier.lower()))
    if tokens&{'bird','birds','eagle','duck','seagull','pigeon','owl','hawk','sparrow'}:return 'bird'
    if tokens&{'airplane','aircraft','aeroplane','helicopter','jet'}:return 'airplane'
    return None


def baseline_prediction(pair,native_size,source_index):
    preferred=pair[source_index] if source_index<len(pair) else None
    for item in (preferred or {}).get('labels',[]):
        if item.get('source')=='camera-trained' and native_size>=item.get('minimum_native_size',8) and item['confidence']>=item.get('threshold',1):return item['identifier']
    if native_size<16:return 'unknown'
    scores=[]
    for result in pair:
        values={}
        for item in (result or {}).get('labels',[]):
            if item.get('source')=='camera-trained':continue
            label=label_category(item['identifier'])
            if label:values[label]=max(values.get(label,0),item['confidence'])
        scores.append(values)
    for label in ('bird','airplane'):
        if sum(s.get(label,0)>=.8 for s in scores)>=2:return label
    if native_size>=32:
        best=max(((v,k) for s in scores for k,v in s.items()),default=(0,'unknown'))
        if best[0]>=.97:return best[1]
    return 'unknown'


def metrics(truth,predicted):
    result={}
    for label in ('bird','airplane'):
        tp=sum(t==label and p==label for t,p in zip(truth,predicted))
        fp=sum(t!=label and p==label for t,p in zip(truth,predicted))
        fn=sum(t==label and p!=label for t,p in zip(truth,predicted))
        precision=tp/(tp+fp) if tp+fp else 0.;recall=tp/(tp+fn) if tp+fn else 0.
        result[label]=dict(tp=tp,fp=fp,fn=fn,precision=precision,recall=recall,f1=2*precision*recall/(precision+recall) if precision+recall else 0.)
    tp=sum(r['tp'] for r in result.values());fp=sum(r['fp'] for r in result.values())
    result['precision']=tp/(tp+fp) if tp+fp else 0.;result['macro_f1']=sum(result[c]['f1'] for c in ('bird','airplane'))/2
    result['cloud_false_suppression']=sum(t!='cloud' and p=='cloud' for t,p in zip(truth,predicted))
    return result


def calibration_thresholds(rows,predictions,classes):
    thresholds={}
    for label in classes:
        best=None
        for threshold in (.85,.9,.93,.95,.97,.99,.995):
            if label=='cloud' and threshold<.95:continue
            chosen=[(r,p) for r,p in zip(rows,predictions) if p['identifier']==label and p['confidence']>=threshold]
            tp=sum(r['label']==label for r,p in chosen);fp=len(chosen)-tp
            sessions={r['session_id'] for r,p in chosen if r['label']==label}
            if tp<2 or len(sessions)<2 or fp:continue
            candidate=(tp,threshold)
            if best is None or candidate[0]>best[0]:best=candidate
        thresholds[label]=best[1] if best else 1.1
    return thresholds


def train(folder):
    os.environ.setdefault('OMP_NUM_THREADS','2')
    emit(folder,'initializing',progress=3,message='Loading transfer-learning tools')
    import numpy as np
    from PIL import Image
    import torch
    import torchvision
    from torchvision import transforms
    from torchvision.models import mobilenet_v3_small,MobileNet_V3_Small_Weights
    from sklearn.linear_model import LogisticRegression
    torch.set_num_threads(2);torch.manual_seed(731);np.random.seed(731)
    dataset=json.loads((folder/'dataset.json').read_text());classes=dataset['classes'];rows=dataset['samples']
    train_rows=[r for r in rows if r['split']=='train'];cal_rows=[r for r in rows if r['split']=='calibration'];test_rows=[r for r in rows if r['split']=='test']
    emit(folder,'extracting_features',progress=5,message='Learning camera-specific appearances',counts=dataset['split_counts'])
    net=mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT).eval()
    class Embedding(torch.nn.Module):
        def __init__(self,model):
            super().__init__();self.features=model.features;self.avgpool=model.avgpool;self.prehead=torch.nn.Sequential(*list(model.classifier.children())[:2])
        def forward(self,x):return self.prehead(torch.flatten(self.avgpool(self.features(x)),1))
    embedding=Embedding(net).eval()
    device='mps' if torch.backends.mps.is_available() else 'cpu';embedding.to(device)
    basic=transforms.Compose([transforms.Resize((224,224),interpolation=transforms.InterpolationMode.BILINEAR),transforms.ToTensor(),transforms.Normalize([.485,.456,.406],[.229,.224,.225])])
    augment=transforms.Compose([transforms.RandomAffine(degrees=8,translate=(.05,.05),scale=(.9,1.1)),transforms.ColorJitter(brightness=.12,contrast=.12,saturation=.08)])
    tensors=[];targets=[]
    for row in train_rows:
        im=Image.open(folder/row['image']).convert('RGB')
        for view in range(12):tensors.append(basic(im if view==0 else augment(im)));targets.append(classes.index(row['label']))
    features=[]
    with torch.no_grad():
        for start in range(0,len(tensors),16):
            batch=torch.stack(tensors[start:start+16]).to(device);features.append(embedding(batch).cpu().numpy())
            emit(folder,'extracting_features',progress=5+int(40*min(start+16,len(tensors))/len(tensors)),samples_done=min(start+16,len(tensors)),samples_total=len(tensors),device=device)
    x=np.concatenate(features);y=np.asarray(targets)
    emit(folder,'training',progress=48,message='Fitting the camera classifier')
    classifier=LogisticRegression(C=.5,class_weight='balanced',max_iter=2000,random_state=731).fit(x,y)
    if list(classifier.classes_)!=list(range(len(classes))):raise ValueError('A training class has no examples')
    head=torch.nn.Linear(x.shape[1],len(classes))
    coef=classifier.coef_;bias=classifier.intercept_
    if len(classes)==2:coef=np.concatenate((-coef/2,coef/2));bias=np.concatenate((-bias/2,bias/2))
    with torch.no_grad():head.weight.copy_(torch.tensor(coef,dtype=torch.float32));head.bias.copy_(torch.tensor(bias,dtype=torch.float32))
    class CameraModel(torch.nn.Module):
        def __init__(self,features,head):
            super().__init__();self.features=features;self.head=head
            self.register_buffer('mean',torch.tensor([.485,.456,.406]).reshape(1,3,1,1));self.register_buffer('std',torch.tensor([.229,.224,.225]).reshape(1,3,1,1))
        def forward(self,image):return torch.softmax(self.head(self.features((image-self.mean)/self.std)),dim=1)
    model=CameraModel(embedding.to('cpu'),head).eval()
    emit(folder,'exporting',progress=55,message='Exporting the candidate for the Mac inference worker')
    import coremltools as ct
    traced=torch.jit.trace(model,torch.rand(1,3,224,224),check_trace=False)
    coreml=ct.convert(traced,inputs=[ct.ImageType(name='image',shape=(1,3,224,224),scale=1/255)],
        classifier_config=ct.ClassifierConfig(classes),minimum_deployment_target=ct.target.macOS13,compute_precision=ct.precision.FLOAT32)
    package=folder/'camera.mlpackage';coreml.save(str(package));torch.save(model.state_dict(),folder/'camera-weights.pt')
    compiled=folder/'camera.mlmodelc'
    subprocess.run([str(ROOT/'vision_worker'),'--compile',str(package),str(compiled)],check=True,stdout=sys.stderr,timeout=180)
    parity=[]
    for row in test_rows[:5]:
        im=Image.open(folder/row['image']).convert('RGB').resize((224,224),Image.Resampling.BILINEAR)
        with torch.no_grad():pred=model(transforms.ToTensor()(im).unsqueeze(0)).numpy()[0]
        converted=coreml.predict({'image':im})
        probabilities=next(v for v in converted.values() if isinstance(v,dict))
        delta=max(abs(float(pred[i])-float(probabilities[label])) for i,label in enumerate(classes));parity.append(delta)
    if max(parity,default=0)>.025:raise ValueError('Export parity check failed')
    policy=dict(version=folder.name,compiled_path=str(compiled),thresholds={c:0. for c in classes},minimum_native_size=8,kind='camera-crop-mobilenet-v3')
    policy_path=folder/'candidate-policy.json';write(policy_path,policy)
    emit(folder,'calibrating',progress=68,message='Calibrating on separate recording sessions')
    cal_results=invoke_vision([folder/r['image'] for r in cal_rows],policy_path)
    def custom_prediction(result):
        return next((v for v in result['labels'] if v.get('source')=='camera-trained'),dict(identifier='unknown',confidence=0))
    cal_predictions=[custom_prediction(r) for r in cal_results]
    thresholds=calibration_thresholds(cal_rows,cal_predictions,classes);policy['thresholds']=thresholds;write(policy_path,policy)
    emit(folder,'evaluating',progress=78,message='Testing against the active model on held-out recordings')
    pair_images=[];pair_indices=[]
    for row in test_rows:
        indexes=[]
        for name in row['pair']:
            if name:indexes.append(len(pair_images));pair_images.append(folder/name)
            else:indexes.append(None)
        pair_indices.append(indexes)
    old_results=invoke_vision(pair_images)
    baseline=[]
    for row,indices in zip(test_rows,pair_indices):baseline.append(baseline_prediction([old_results[i] if i is not None else None for i in indices],row['native_size'],row['source_index']))
    new_results=invoke_vision([folder/r['image'] for r in test_rows],policy_path)
    proposed=[]
    for row,result,old in zip(test_rows,new_results,baseline):
        custom=custom_prediction(result)
        proposed.append(custom['identifier'] if custom['confidence']>=thresholds.get(custom['identifier'],1.1) and row['native_size']>=8 else old)
    truth=[r['label'] for r in test_rows];old_metrics=metrics(truth,baseline);new_metrics=metrics(truth,proposed)
    reasons=[]
    for label in ('bird','airplane'):
        if thresholds.get(label,1.1)>1:reasons.append('Not enough accurate calibration examples for '+label)
        if sum(t==label for t in truth)<2:reasons.append('Too few held-out '+label+' examples')
        if new_metrics[label]['recall']<old_metrics[label]['recall']:reasons.append(label+' recall declined')
    if new_metrics['precision']<.9:reasons.append('Held-out object precision below 90%')
    if new_metrics['macro_f1']<old_metrics['macro_f1']+.03:reasons.append('Held-out bird/airplane F1 did not improve enough')
    if new_metrics['cloud_false_suppression']:reasons.append('Candidate incorrectly classified an object as cloud')
    report=dict(version=folder.name,passed=not reasons,reasons=reasons,classes=classes,thresholds=thresholds,minimum_native_size=8,
        baseline=old_metrics,candidate=new_metrics,split_counts=dataset['split_counts'],session_counts=dataset['session_counts'],
        fingerprint=dataset['fingerprint'],export_max_error=max(parity,default=0),training_iterations=classifier.n_iter_.tolist(),
        torch_version=torch.__version__,torchvision_version=torchvision.__version__,coremltools_version=ct.__version__,
        tests=[dict(id=r['id'],session_id=r['session_id'],truth=t,baseline=old,candidate=new) for r,t,old,new in zip(test_rows,truth,baseline,proposed)],
        note='Pilot evaluation on a small camera-specific dataset; label-only inference, all captures retained.')
    write(folder/'evaluation.json',report)
    emit(folder,'candidate_ready' if report['passed'] else 'rejected',progress=95,report=report,message='Candidate passed evaluation' if report['passed'] else '; '.join(reasons))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--receive',action='store_true');parser.add_argument('--sha256');args=parser.parse_args()
    if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{8}',args.run):raise ValueError('Invalid training run')
    folder=ROOT/'training-runs'/args.run;folder.mkdir(parents=True,exist_ok=True)
    if args.receive:
        blob=sys.stdin.buffer.read(30*1024**2+1)
        if len(blob)>30*1024**2 or hashlib.sha256(blob).hexdigest()!=args.sha256:raise ValueError('Dataset checksum or size invalid')
        archive=folder/'dataset.tar.gz';archive.write_bytes(blob)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                path=Path(member.name)
                if path.is_absolute() or '..' in path.parts or not(member.isfile() or member.isdir()):raise ValueError('Unsafe dataset archive')
            tar.extractall(folder,filter='data')
        print('received',flush=True);return
    with (ROOT/'training.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:train(folder)
        except Exception as error:
            emit(folder,'failed',error=str(error),message='Training failed; the active model was not changed')
            raise

if __name__=='__main__':main()
