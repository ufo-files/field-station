"""Background shape measurements and conservative, label-only object recognition."""
import base64
from collections import deque
import io
import json
import math
from pathlib import Path
import queue
import re
import shlex
import subprocess
import threading
import time
import numpy as np
from PIL import Image
from experiments import load,save,utc
from m1_encode import ssh_args
from classification_labels import label_text,matching_region,effective_classification

VERSION=1
OBJECT_LABELS=('bird','airplane','other_animal','unknown')
SHAPE_LABELS=('round','elongated','irregular','too_small','unresolved')


def shape_measurement(image, box):
    """Measure a segmented single-frame silhouette, never the motion difference."""
    from motion_trigger import changed_regions
    w,h=image.size
    l,t,r,b=[int(box[k]) for k in ('left','top','right','bottom')]
    l=max(0,l-10);t=max(0,t-10);r=min(w,r+10);b=min(h,b+10)
    if r<=l or b<=t:return dict(label='unresolved',reason='Invalid region')
    a=np.asarray(image.convert('L').crop((l,t,r,b)),dtype=np.float32)
    border=np.concatenate((a[0],a[-1],a[:,0],a[:,-1]))
    background=float(np.median(border));mad=float(np.median(np.abs(border-background)))
    threshold=max(8.,4*mad,float(np.percentile(np.abs(a-background),99))*.2)
    mask=np.abs(a-background)>=threshold
    regions=changed_regions(mask)
    # Prefer detail inside the original detected region, rather than nearby clutter.
    regions=[q for q in regions if q['right']>box['left']-l and q['left']<box['right']-l
             and q['bottom']>box['top']-t and q['top']<box['bottom']-t]
    if not regions:return dict(label='unresolved',reason='No separable silhouette',contrast_threshold=threshold)
    q=regions[0];part=mask[q['top']:q['bottom'],q['left']:q['right']]
    # Flood only this connected component; other components can share its bounds.
    seen=np.zeros_like(part);ys,xs=np.nonzero(part)
    if not len(xs):return dict(label='unresolved',reason='No silhouette')
    stack=[(int(ys[0]),int(xs[0]))]
    while stack:
        y,x=stack.pop()
        if y<0 or x<0 or y>=part.shape[0] or x>=part.shape[1] or seen[y,x] or not part[y,x]:continue
        seen[y,x]=True
        stack.extend((y+dy,x+dx) for dy in (-1,0,1) for dx in (-1,0,1) if dy or dx)
    ys,xs=np.nonzero(seen);area=len(xs);bw=q['right']-q['left'];bh=q['bottom']-q['top']
    metrics=dict(area_pixels=area,width_pixels=bw,height_pixels=bh,contrast_threshold=round(threshold,2))
    if min(bw,bh)<8 or area<40:return dict(label='too_small',reason='Insufficient native silhouette detail',**metrics)
    pad=np.pad(seen.astype(np.int8),1)
    perimeter=int(np.abs(np.diff(pad,axis=0)).sum()+np.abs(np.diff(pad,axis=1)).sum())
    circularity=4*math.pi*area/max(1,perimeter**2)
    eig=np.linalg.eigvalsh(np.cov(np.stack((xs,ys))))
    axis_ratio=math.sqrt(max(0,float(eig[0]))/max(1e-6,float(eig[1])))
    fill=area/(bw*bh)
    label='round' if axis_ratio>=.78 and circularity>=.52 and fill>=.55 else 'elongated' if axis_ratio<.48 else 'irregular'
    # Clipped silhouettes cannot establish shape.
    if q['left']==0 or q['top']==0 or q['right']==a.shape[1] or q['bottom']==a.shape[0]:
        label='unresolved'
    return dict(label=label,circularity=round(circularity,3),axis_ratio=round(axis_ratio,3),
                fill_fraction=round(fill,3),**metrics)


def category(identifier):
    tokens=set(re.split(r'[^a-z]+',identifier.lower()))
    if tokens & {'bird','birds','eagle','seagull','duck','pigeon','owl','hawk','sparrow'}:return 'bird'
    if tokens & {'airplane','aircraft','aeroplane','helicopter','jet'}:return 'airplane'
    if tokens & {'animal','animals','mammal','dog','cat','deer','bat','insect','butterfly','horse','cow'}:return 'other_animal'
    return None


def decide_object(observations, native_size, preferred_index=None):
    order=[preferred_index] if preferred_index is not None and preferred_index<len(observations) else range(len(observations))
    for index in order:
        candidates=[v for v in observations[index] if v.get('source')=='camera-trained'
                    and native_size>=v.get('minimum_native_size',8) and v.get('confidence',0)>=v.get('threshold',1.1)
                    and v.get('identifier') in ('bird','airplane','cloud','insect','other_animal','balloon','star','satellite','shooting_star','house','antenna','vehicle','telephone_pole','mountain','drone','tree')]
        if candidates:
            best=max(candidates,key=lambda v:v['confidence'])
            return dict(label=best['identifier'],confidence=round(best['confidence'],3),support_frames=1,
                        model_version=best.get('model_version'),reason='Camera-trained model suggestion at validated threshold')
    evidence=[]
    for labels in observations:
        scores={}
        for item in labels:
            if item.get('source')=='camera-trained':continue
            label=category(item['identifier'])
            if label:scores[label]=max(scores.get(label,0),float(item['confidence']))
        evidence.append(scores)
    if native_size<16:
        return dict(label='unknown',reason='Target too small for reliable object identification',support_frames=0)
    for label in OBJECT_LABELS[:-1]:
        support=[v[label] for v in evidence if v.get(label,0)>=.8]
        if len(support)>=2:
            return dict(label=label,confidence=round(min(support),3),support_frames=len(support),
                        reason='Model agreement in both comparison frames; label only')
    if native_size>=32:
        suggestions=[(score,label) for scores in evidence for label,score in scores.items() if score>=.97]
        if suggestions:
            score,label=max(suggestions)
            if all(not any(other!=label and value>=.8 for other,value in scores.items()) for scores in evidence):
                return dict(label=label,confidence=round(score,3),support_frames=1,
                            reason='Strong single-frame suggestion; not validated for capture suppression')
    return dict(label='unknown',reason='No consistent high-confidence object label',support_frames=0)


def crop_for_model(image,box):
    w,h=image.size
    cx=(box['left']+box['right'])/2;cy=(box['top']+box['bottom'])/2
    radius=max(24,(box['right']-box['left'])*.8,(box['bottom']-box['top'])*.8)
    crop=image.crop((max(0,int(cx-radius)),max(0,int(cy-radius)),min(w,int(cx+radius)),min(h,int(cy+radius))))
    crop.thumbnail((384,384));output=io.BytesIO();crop.save(output,format='JPEG',quality=94)
    return base64.b64encode(output.getvalue()).decode()


class ObjectAnalysis:
    def __init__(self,station,root):
        self.station=station;self.root=Path(root);self.jobs=queue.PriorityQueue(maxsize=128)
        self.backlog=deque()
        self.pending=set();self.lock=threading.RLock();self.current=None;self.error=None;self.completed=0;self.live_result=None
        self.observed_model=load(self.root/'run/active-model.json',{}).get('version','baseline-yolov3')
        self.model_checked=0
        self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()
    def status(self):
        return dict(mode='label_only',engine='coreml_yolov3',queued=self.jobs.qsize()+len(self.backlog),processing=self.current,
                    completed=self.completed,error=self.error,version=VERSION)
    def decorate_overlay(self,data):
        result=self.live_result
        regions=result['regions'] if result and time.time()-result['detected_epoch']<5 else []
        width=data.get('width',1920);height=data.get('height',1080)
        decorated=[]
        for box in data.get('boxes',[]):
            native=dict(left=box['left']*1920/width,right=box['right']*1920/width,
                        top=box['top']*1080/height,bottom=box['bottom']*1080/height)
            match=matching_region(native,regions)
            if match and match.get('object',{}).get('label')=='cloud':continue
            decorated.append(dict(box,label=label_text(match) if match else 'Motion | analyzing'))
        output=dict(data,boxes=decorated)
        target=data.get('manual_target')
        if target:
            match=matching_region(target,regions)
            output['manual_target']=None if match and match.get('object',{}).get('label')=='cloud' else dict(target,label=label_text(match) if match else 'Selected target')
        return output

    def enqueue(self,sid,eid,priority=0):
        if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid) or not re.fullmatch(r'[a-f0-9]{16}',eid):
            raise ValueError('Invalid motion event')
        key=(sid,eid)
        with self.lock:
            if key in self.pending:return dict(state='queued')
            if self.jobs.full():raise ValueError('Classification queue is full; try again shortly')
            self.pending.add(key);self.jobs.put_nowait((priority,time.monotonic_ns(),sid,eid))
        return dict(state='queued')
    def request(self,body):
        sid=str(body.get('session_id',''));eid=str(body.get('event_id',''))
        folder=self.station.data_path(sid) if re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid) else None
        if folder is None or not (folder/f'motion-{eid}-after.jpg').is_file():raise ValueError('Original event frames are not available locally')
        return self.enqueue(sid,eid)
    def remote(self,images):
        config=load(self.root/'private/m1/config.json',{})
        if not config.get('enabled'):raise ValueError('Mac classification worker is disabled')
        executable=str(Path(config['worker']).with_name('vision_worker'))
        result=subprocess.run(ssh_args(config)+[shlex.quote(executable)],input=json.dumps(dict(images=images)).encode(),
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
        if result.returncode:raise OSError('Mac classifier failed: '+result.stderr.decode(errors='replace')[-250:])
        response=json.loads(result.stdout)
        if len(response.get('results',[]))!=len(images):raise ValueError('Incomplete classifier response')
        self.inference_version=response.get('model_version','baseline-yolov3')
        self.inference_engine=response.get('engine','coreml-yolov3-fp16-coco')
        self.inference_error=response.get('model_error')
        return response['results']
    def analyze(self,folder,event):
        originals=[Image.open(folder/f"motion-{event['id']}-{suffix}.jpg").convert('RGB') for suffix in ('before','after')]
        annotation=event.get('annotation',{})
        regions=annotation.get('changed_regions') or annotation.get('boxes') or event.get('small_motion_regions') or []
        if not regions and event.get('selected_point'):
            point=event['selected_point'];x=point['x']*originals[0].width;y=point['y']*originals[0].height
            regions=[dict(left=x-12,top=y-12,right=x+12,bottom=y+12)]
        regions=sorted(regions,key=lambda b:(b['right']-b['left'])*(b['bottom']-b['top']),reverse=True)[:3]
        items=[];crops=[]
        for b in regions:
            source=0 if b.get('visible_in',annotation.get('source_frame'))=='before' else 1
            shape=shape_measurement(originals[source],b)
            items.append(dict(bounds={k:int(b[k]) for k in ('left','top','right','bottom')},shape=shape,source_frame=('before','after')[source]))
            crops.extend(crop_for_model(im,b) for im in originals)
        results=[];remote_error=None
        if crops:
            try:results=self.remote(crops)
            except (OSError,ValueError,subprocess.TimeoutExpired) as e:remote_error=str(e)
        for i,item in enumerate(items):
            pair=results[i*2:i*2+2]
            labels=[r.get('labels',[]) for r in pair]
            b=item['bounds'];size=max(b['right']-b['left'],b['bottom']-b['top'])
            item['object']=decide_object(labels,size,0 if item['source_frame']=='before' else 1)
            item['model_observations']=pair
            if any(r.get('error') for r in pair):remote_error='; '.join(r['error'] for r in pair if r.get('error'))
        return dict(version=VERSION,state='completed',mode='label_only',classified_at=utc(),
                    engine=getattr(self,'inference_engine','coreml-yolov3-fp16-coco'),model_version=getattr(self,'inference_version','baseline-yolov3'),regions=items,error=remote_error or getattr(self,'inference_error',None),
                    meaning='Shape is single-frame appearance; object labels are model suggestions. All captures are retained.')
    def persist(self,sid,eid,result):
        with self.station.lock:
            folder=self.station.data_path(sid);events=load(folder/'motion-events.json',[])
            event=next((e for e in events if e['id']==eid),None)
            if not event:return
            event['classification']=result
            mbox=folder/f'motion-{eid}-boxed.jpg'
            from motion_trigger import annotate_motion
            if event.get('human_review'):
                from boxed_review import render_review
                key=sid+'--'+mbox.name
                snapshot=self.station.boxed_review.images/(key+'.jpg')
                source=self.station.boxed_review.image(key,True)
                event['annotation']=render_review(Image.open(source),event['human_review'],mbox)
            else:
                event['annotation']=annotate_motion((folder/f'motion-{eid}-before.jpg').read_bytes(),
                    (folder/f'motion-{eid}-after.jpg').read_bytes(),event['settings'],mbox,classification=result)
            self.live_result=dict(detected_epoch=event.get('detected_epoch',0),regions=effective_classification(event)['regions'])
            save(folder/'motion-events.json',events)
            m=load(folder/'manifest.json',{})
            for e in m.get('motion_events',[]):
                if e['id']==eid:e['classification']=result
            # The updated evidence JSON changed its checksum; do not leave stale integrity metadata.
            from experiments import file_info
            m.setdefault('files',{})['motion-events.json']=file_info(folder/'motion-events.json')
            if mbox:m['files'][mbox.name]=file_info(mbox)
            for crop in event.get('annotation',{}).get('detail_images',[]):
                for name in (crop['native_file'],crop['detail_file']):m['files'][name]=file_info(folder/name)
            for entry in m.get('motion_events',[]):
                if entry['id']==eid:entry['annotation']=event.get('annotation',{})
            active=self.station.active
            if active and active['id']==sid:
                for e in active.get('motion_events',[]):
                    if e['id']==eid:
                        e['classification']=result
                        e['annotation']=event.get('annotation',{})
                if mbox:active.setdefault('files',{})[mbox.name]=m['files'][mbox.name]
                for crop in event.get('annotation',{}).get('detail_images',[]):
                    for name in (crop['native_file'],crop['detail_file']):active.setdefault('files',{})[name]=m['files'][name]
                active.setdefault('files',{})['motion-events.json']=m['files']['motion-events.json']
            save(folder/'manifest.json',m)
            trigger=getattr(self.station,'motion_trigger',None)
            if trigger and (trigger.last_event or {}).get('id')==eid:
                trigger.last_event['classification']=result
    def recover_recent(self):
        # Bounded recovery: new events have priority over historical backfill.
        folders=sorted(self.station.data_path('').glob('*/motion-events.json'),reverse=True)
        for path in folders:
            for event in reversed(load(path,[])):
                if event.get('classification',{}).get('source')=='uap-lab':continue
                if (event.get('classification',{}).get('version')!=VERSION or (self.observed_model!='baseline-yolov3' and not event.get('human_review') and event.get('classification',{}).get('model_version')!=self.observed_model)) and (path.parent/f"motion-{event['id']}-after.jpg").exists():
                    self.backlog.append((path.parent.name,event['id']))
    def work(self):
        # Allow Station initialization to finish before touching its data/lock.
        if self.station.exiting.wait(2):return
        try:self.recover_recent()
        except (OSError,ValueError) as e:self.error=str(e)
        while not self.station.exiting.is_set():
            if time.monotonic()-self.model_checked>10:
                self.model_checked=time.monotonic()
                version=load(self.root/'run/active-model.json',{}).get('version','baseline-yolov3')
                if version!=self.observed_model:
                    self.observed_model=version;self.recover_recent()
            while self.backlog and self.jobs.qsize()<8:
                sid,eid=self.backlog.popleft();self.enqueue(sid,eid,priority=10)
            try:_,_,sid,eid=self.jobs.get(timeout=1)
            except queue.Empty:continue
            self.current=dict(session_id=sid,event_id=eid)
            try:
                folder=self.station.data_path(sid)
                event=next((e for e in load(folder/'motion-events.json',[]) if e['id']==eid),None)
                if event is None:continue
                result=self.analyze(folder,event)
                self.persist(sid,eid,result)
                self.error=result.get('error');self.completed+=1
            except (OSError,ValueError,KeyError) as error:self.error=str(error)
            finally:
                with self.lock:self.pending.discard((sid,eid))
                self.current=None;self.jobs.task_done()
