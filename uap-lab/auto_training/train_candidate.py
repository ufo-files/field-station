"""Resource-bounded, immutable candidate training. Never activates or publishes a model."""
import argparse,fcntl,hashlib,json,os,time
from pathlib import Path
from training_policy import calibrate,evaluate

def save(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2));temp.replace(path)
def train(folder):
    os.environ['OMP_NUM_THREADS']='2';os.environ['OPENBLAS_NUM_THREADS']='2';os.environ['VECLIB_MAXIMUM_THREADS']='2'
    def status(phase,**extra):save(folder/'status.json',dict(phase=phase,updated_epoch=time.time(),automatic_promotion=False,**extra))
    import numpy as np
    import torch
    import torchvision
    from PIL import Image
    from torchvision import transforms
    from torchvision.models import mobilenet_v3_small,MobileNet_V3_Small_Weights
    from sklearn.linear_model import LogisticRegression
    from threadpoolctl import threadpool_limits
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(731);np.random.seed(731)
    dataset=json.loads((folder/'dataset.json').read_text());rows=dataset['samples'];classes=dataset['classes']
    if dataset['blockers']:raise ValueError('Dataset has unresolved split blockers')
    for role in ['train','calibration','test']:
        if not any(r['split']==role for r in rows):raise ValueError('Missing independent '+role+' split')
    if any(len({r['split'] for r in rows if r['group']==group})!=1 for group in {r['group'] for r in rows}):raise ValueError('Recording leakage between splits')
    status('loading_pretrained_features',resources=dict(cpu_threads=2,feature_batch=16,device='cpu'))
    weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1;net=mobilenet_v3_small(weights=weights).eval()
    class Features(torch.nn.Module):
        def __init__(self,base):
            super().__init__();self.features=base.features;self.pool=base.avgpool;self.prehead=torch.nn.Sequential(*list(base.classifier.children())[:2])
            self.register_buffer('mean',torch.tensor([.485,.456,.406]).reshape(1,3,1,1));self.register_buffer('std',torch.tensor([.229,.224,.225]).reshape(1,3,1,1));self.register_buffer('gray',torch.tensor([.299,.587,.114]).reshape(1,3,1,1))
        def forward(self,image):
            gray=(image*self.gray).sum(dim=1,keepdim=True).repeat(1,3,1,1)
            return self.prehead(torch.flatten(self.pool(self.features((gray-self.mean)/self.std)),1))
    embedding=Features(net).eval();basic=transforms.Compose([transforms.Resize((224,224),interpolation=transforms.InterpolationMode.BILINEAR),transforms.ToTensor()]);augment=transforms.Compose([transforms.RandomAffine(degrees=8,translate=(.05,.05),scale=(.9,1.1)),transforms.ColorJitter(brightness=.12,contrast=.12)])
    def tensors(selected,views):
        for row in selected:
            path=folder/row['image']
            if not path.resolve().is_relative_to(folder.resolve()) or path.is_symlink():raise ValueError('Unsafe image path')
            with Image.open(path) as source:
                im=source.convert('RGB')
                digest=hashlib.sha256(f'{im.width}x{im.height}:RGB:'.encode()+im.tobytes()).hexdigest()
                if digest!=row['pixel_sha256']:raise ValueError('Training crop pixel checksum changed')
                for view in range(views):yield basic(im if view==0 else augment(im)),classes.index(row['label'])
    def features(selected,views,phase):
        result=[];targets=[];batch=[];batch_y=[];done=0
        def flush():
            nonlocal done
            if not batch:return
            with torch.no_grad():result.append(embedding(torch.stack(batch)).numpy())
            targets.extend(batch_y);done+=len(batch);batch.clear();batch_y.clear();status(phase,processed=done,total=len(selected)*views)
        for image,label in tensors(selected,views):
            batch.append(image);batch_y.append(label)
            if len(batch)==16:flush()
        flush();return np.concatenate(result),np.asarray(targets)
    training=[r for r in rows if r['split']=='train'];calibration=[r for r in rows if r['split']=='calibration'];testing=[r for r in rows if r['split']=='test']
    x,y=features(training,3,'training_features');status('fitting_head')
    with threadpool_limits(limits=2):head_fit=LogisticRegression(C=.5,class_weight='balanced',max_iter=2000,random_state=731).fit(x,y)
    if list(head_fit.classes_)!=list(range(len(classes))):raise ValueError('Training class missing')
    head=torch.nn.Linear(x.shape[1],len(classes));coef=head_fit.coef_;bias=head_fit.intercept_
    if len(classes)==2:coef=np.concatenate((-coef/2,coef/2));bias=np.concatenate((-bias/2,bias/2))
    with torch.no_grad():head.weight.copy_(torch.tensor(coef,dtype=torch.float32));head.bias.copy_(torch.tensor(bias,dtype=torch.float32))
    class Candidate(torch.nn.Module):
        def __init__(self,features,head):super().__init__();self.features=features;self.head=head
        def forward(self,image):return torch.softmax(self.head(self.features(image)),dim=1)
    candidate=Candidate(embedding,head).eval()
    cal_x,_=features(calibration,1,'calibration_features');test_x,_=features(testing,1,'test_features')
    with torch.no_grad():cal_p=torch.softmax(head(torch.tensor(cal_x)),dim=1).numpy();test_p=torch.softmax(head(torch.tensor(test_x)),dim=1).numpy()
    thresholds,cal_evidence=calibrate(calibration,cal_p,classes);report=evaluate(testing,test_p,classes,thresholds)
    status('converting_coreml');import coremltools as ct
    traced=torch.jit.trace(candidate,torch.rand(1,3,224,224),check_trace=False)
    model=ct.convert(traced,inputs=[ct.ImageType(name='image',shape=(1,3,224,224),scale=1/255)],classifier_config=ct.ClassifierConfig(classes),minimum_deployment_target=ct.target.macOS13,compute_precision=ct.precision.FLOAT32)
    if (folder/'candidate.mlpackage').exists():(folder/'candidate.mlpackage').rename(folder/('candidate-attempt-'+str(time.time_ns())+'.mlpackage'))
    model.save(str(folder/'candidate.mlpackage'));torch.save(candidate.state_dict(),folder/'candidate-weights.pt')
    parity=[]
    for row in testing[:10]:
        with Image.open(folder/row['image']) as im:im=im.convert('RGB').resize((224,224),Image.Resampling.BILINEAR)
        with torch.no_grad():original=candidate(transforms.ToTensor()(im).unsqueeze(0)).numpy()[0]
        output=model.predict({'image':im});scores=next(v for v in output.values() if isinstance(v,dict));parity.append(max(abs(float(original[i])-float(scores[label])) for i,label in enumerate(classes)))
    report.update(dataset_fingerprint=dataset['fingerprint'],classes=classes,thresholds=thresholds,calibration=cal_evidence,export_max_absolute_error=max(parity,default=1),automatic_promotion=False,pipeline_qualified=False,limitations=['Crop-level evaluation only; native proposal recall, tracking and full-load throughput unqualified','Anomalous means similarity to reviewed examples, not proof of an unexplained event','Small or uncertain objects remain unknown and retain evidence'],versions=dict(torch=torch.__version__,torchvision=torchvision.__version__,coremltools=ct.__version__),resources=dict(cpu_threads=2,feature_batch=16,device='cpu'))
    save(folder/'evaluation.json',report)
    if report['export_max_absolute_error']>.025:raise ValueError('Core ML export parity failed')
    save(folder/'candidate-policy.json',dict(schema_version=1,version=dataset['fingerprint'],classes=classes,thresholds=thresholds,minimum_native_size=8,preprocessing='grayscale conversion embedded in model',role='review_suggestions_only',automatic_promotion=False))
    status('candidate_ready_for_shadow',evaluation='evaluation.json',dataset_fingerprint=dataset['fingerprint'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True);p.add_argument('--lock',type=Path,required=True);a=p.parse_args();os.nice(5)
    existing=json.loads((a.folder/'candidate-policy.json').read_text()) if (a.folder/'candidate-policy.json').exists() else {}
    dataset=json.loads((a.folder/'dataset.json').read_text())
    if existing.get('version')==dataset['fingerprint'] and (a.folder/'evaluation.json').exists() and (a.folder/'candidate.mlpackage').is_dir():
        save(a.folder/'status.json',dict(phase='candidate_ready_for_shadow',recovered=True,automatic_promotion=False));raise SystemExit(0)
    save(a.folder/'status.json',dict(phase='waiting_for_batch_lock',updated_epoch=time.time(),automatic_promotion=False))
    try:
        with a.lock.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);train(a.folder)
    except Exception as exc:
        save(a.folder/'status.json',dict(phase='failed',error=str(exc),updated_epoch=time.time(),automatic_promotion=False));raise
