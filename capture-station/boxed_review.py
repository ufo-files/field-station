"""Web review, durable observer corrections, and clean training snapshots."""
import copy
import io
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
from PIL import Image,ImageDraw,ImageFont
from experiments import load,save,utc,file_info
from review_video import event_position
from motion_details import save_detail,save_motion_details,crop_geometry
from classification_labels import effective_classification,label_text,matching_region

KEY=re.compile(r'([0-9TZ]+-[a-f0-9]{6})--motion-([a-f0-9]{16})-boxed\.jpg')
OBJECTS=('bird','airplane','other_animal','insect','balloon','star','satellite','shooting_star','house','antenna','vehicle','telephone_pole','mountain','landscape','drone','tree','cloud','anomalous','unknown','no_object')
SHAPES=('round','elongated','irregular','too_small','unresolved')


def render_review(image, review, target):
    original=image.convert('RGB').copy();draw=ImageDraw.Draw(original);font=ImageFont.load_default(size=18)
    boxes=[]
    for number,r in enumerate(review['regions'],1):
        if r['object']=='cloud':continue
        b=dict(r['bounds']);rect=(max(0,b['left']-16),max(0,b['top']-16),min(original.width-1,b['right']+16),min(original.height-1,b['bottom']+16))
        region=dict(bounds=b,object=dict(label=r['object'],source='human'),shape=dict(label=r['shape']))
        title=f'T{number}: '+label_text(region);text=draw.textbbox((0,0),title,font=font)
        tx=max(0,min(rect[0],original.width-(text[2]-text[0])-8));ty=max(0,rect[1]-26)
        draw.rectangle(rect,outline='#70f5d0',width=3);draw.rectangle((tx,ty,tx+text[2]-text[0]+6,ty+24),fill='#071013')
        draw.text((tx+3,ty+2),title,font=font,fill='#70f5d0')
        boxes.append(dict(b,label=label_text(region),visible_in=review['source_frame'],review_bounds=dict(zip(('left','top','right','bottom'),rect))))
    if not review['regions']:draw.text((12,12),'REVIEWED: NO OBJECT',font=font,fill='#70f5d0',stroke_fill='black',stroke_width=2)
    if review['regions'] and not boxes:draw.text((12,12),'REVIEWED: CLOUD / BACKGROUND',font=font,fill='#70f5d0',stroke_fill='black',stroke_width=2)
    temporary=target.with_suffix('.review-tmp');original.save(temporary,format='JPEG',quality=95);temporary.replace(target)
    details=save_motion_details(image,boxes,target,review['source_frame'],reviewed=True)
    return dict(boxes=boxes,detail_images=details,source_frame=review['source_frame'],frame_width=original.width,frame_height=original.height,
                annotation_version=3,human_reviewed=True,meaning='Observer-reviewed labels; original images retained.')


class BoxedReview:
    def __init__(self,station,data):
        self.station=station;self.data=Path(data);self.collection=self.data/'boxed-frames'
        self.training=self.data.parent/'training';self.records=self.training/'reviews';self.images=self.training/'images';self.references=self.training/'references'
    def paths(self,key):
        match=KEY.fullmatch(str(key))
        if not match:raise ValueError('Invalid boxed-frame identifier')
        sid,eid=match.groups();folder=self.data/sid
        return sid,eid,folder,self.collection/key
    def event(self,key):
        sid,eid,folder,boxed=self.paths(key)
        if not boxed.is_file():raise ValueError('Boxed frame not found')
        event=next((e for e in load(folder/'motion-events.json',[]) if e.get('id')==eid),{})
        if not event:
            record=load(self.records/(key+'.json'),{})
            event=record.get('event_snapshot',dict(id=eid))
        return sid,eid,folder,boxed,event
    def listing(self,query):
        offset=max(0,int(query.get('offset',['0'])[0]));limit=max(1,min(60,int(query.get('limit',['30'])[0])))
        search=query.get('search',[''])[0].lower();kind=query.get('object',['all'])[0];reviewed=query.get('review',['all'])[0]
        index=load(self.collection/'classification-index.json',{});items=[];counts=dict(total=0,reviewed=0,training_ready=0)
        records={p.name[:-5]:load(p,{}) for p in self.records.glob('*.json')} if self.records.exists() else {}
        for p in sorted(self.collection.glob('*.jpg'),reverse=True):
            if not KEY.fullmatch(p.name):continue
            record=records.get(p.name,{});review=record.get('human_review',{});counts['total']+=1
            counts['reviewed']+=bool(review);counts['training_ready']+=bool(record.get('training_ready'))
            labels=sorted({r['object'] for r in review.get('regions',[])}) if review else index.get(p.name,{}).get('objects',['unknown'])
            if review and not review['regions']:labels=['no_object']
            if search and search not in p.name.lower():continue
            if kind!='all' and kind not in labels:continue
            if reviewed=='reviewed' and not review:continue
            if reviewed=='unreviewed' and review:continue
            if reviewed=='training_ready' and not record.get('training_ready'):continue
            items.append(dict(key=p.name,labels=labels,reviewed=bool(review),training_ready=bool(record.get('training_ready')),
                version=p.stat().st_mtime_ns,image_url='/api/boxed-review/image?key='+p.name))
        return dict(items=items[offset:offset+limit],total=len(items),offset=offset,limit=limit,counts=counts,
                    objects=OBJECTS,shapes=SHAPES)
    def detail(self,key):
        sid,eid,folder,boxed,event=self.event(key)
        review=event.get('human_review') or load(self.records/(key+'.json'),{}).get('human_review')
        source=(review or {}).get('source_frame') or event.get('annotation',{}).get('source_frame','after')
        source=source if source in ('before','after') else 'after'
        clean=folder/f'motion-{eid}-{source}.jpg';snapshot=self.images/(key+'.jpg')
        reference=self.references/(key+'.jpg')
        image=clean if clean.is_file() else snapshot if snapshot.is_file() else reference if reference.is_file() else boxed
        with Image.open(image) as im:w,h=im.size
        regions=[]
        if review:regions=copy.deepcopy(review['regions'])
        else:
            classified=event.get('classification',{}).get('regions',[])
            for b in event.get('annotation',{}).get('boxes',[]):
                bounds={k:b[k] for k in ('left','top','right','bottom')};match=matching_region(bounds,classified) or {}
                regions.append(dict(bounds=bounds,object=match.get('object',{}).get('label','unknown'),shape=match.get('shape',{}).get('label','unresolved')))
        if not regions and not review:
            for r in event.get('classification',{}).get('regions',[]):
                if r.get('source_frame',source)==source:regions.append(dict(bounds=r['bounds'],object=r['object']['label'],shape=r['shape']['label']))
        crops=[]
        for i,r in enumerate(regions):
            bounds=crop_geometry(r['bounds'],w,h,16 if review else None)
            crops.append(dict(image_url='/api/boxed-review/crop?key='+key+'&target='+str(i),
                native_url='/api/boxed-review/crop?native=1&key='+key+'&target='+str(i),
                native_width=bounds['right']-bounds['left'],native_height=bounds['bottom']-bounds['top']))
        return dict(key=key,session_id=sid,event_id=eid,width=w,height=h,source_frame=source,regions=regions,
                    human_review=review,model_classification=event.get('classification'),clean_image=clean.is_file() or snapshot.is_file(),
                    image_url='/api/boxed-review/image?original=1&key='+key,boxed_url='/api/boxed-review/image?key='+key,
                    objects=OBJECTS,shapes=SHAPES,detail_crops=crops,video=self.video_info(key))
    def image(self,key,original=False):
        _,eid,folder,boxed,event=self.event(key)
        if original:
            source=event.get('human_review',{}).get('source_frame') or event.get('annotation',{}).get('source_frame','after')
            if source not in ('before','after'):source='after'
            clean=folder/f'motion-{eid}-{source}.jpg';snapshot=self.images/(key+'.jpg')
            if clean.is_file():return clean
            if snapshot.is_file():return snapshot
            reference=self.references/(key+'.jpg')
            if reference.is_file():return reference
        return boxed
    def crop_image(self,key,target=0,native=False):
        detail=self.detail(key)
        if target<0 or target>=len(detail['regions']):raise ValueError('Select a valid target')
        _,eid,folder,_=self.paths(key)
        with Image.open(self.image(key,True)) as image:
            meta=save_detail(image,detail['regions'][target]['bounds'],folder,
                             f"motion-{eid}-{detail['source_frame']}",16 if detail.get('human_review') else None)
        return folder/meta['native_file' if native else 'detail_file']

    def video_info(self,key):
        sid,eid,folder,boxed,event=self.event(key)
        manifest=load(folder/'manifest.json',{})
        source=event.get('human_review',{}).get('source_frame') or event.get('annotation',{}).get('source_frame','after')
        position=event_position(manifest,event,source)
        base=dict(available=False,approximate=True,event_seconds=position,source_session_id=sid)
        if (folder/'video.mp4').is_file():
            return dict(base,available=True,state='ready',kind='full_recording',url=f'/sessions/{sid}/video.mp4',description='Full recording')
        archived=manifest.get('internet_archive',{})
        if archived.get('verified_at') and archived.get('video_url'):
            return dict(base,available=True,state='ready',kind='archived_recording',url=archived['video_url'],description='Full recording from Internet Archive')
        playback=manifest.get('video_playback',{})
        if playback.get('state')=='internet_archive' and playback.get('url'):
            return dict(base,available=True,state='ready',kind='archived_recording',url=playback['url'],description='Full recording from Internet Archive')
        preview=folder/f'review-{eid}.mp4';metadata=load(folder/f'review-{eid}.json',{})
        if preview.is_file() and metadata:
            return dict(base,available=True,state='ready',kind='event_preview',url=f'/sessions/{sid}/review-{eid}.mp4',
                        event_seconds=metadata['event_seconds'],clip_start_seconds=metadata['start'],
                        description='12-second event preview · 960×540 / 15 fps')
        worker=getattr(self.station,'review_video',None);status=worker.status(key) if worker else dict(state='not_prepared')
        return dict(base,**status,can_prepare=(folder/'video.mkv').is_file(),
                    watch_url=manifest.get('youtube',{}).get('url'),
                    description='A short local event preview can be prepared' if (folder/'video.mkv').is_file() else 'Source video is not available yet')

    def save_review(self,body):
        key=str(body.get('key',''));detail=self.detail(key);sid,eid,folder,boxed,event=self.event(key)
        regions=body.get('regions')
        if not isinstance(regions,list) or len(regions)>32:raise ValueError('Review must contain up to 32 target boxes')
        validated=[]
        for r in regions:
            if r.get('object') not in OBJECTS or r.get('shape') not in SHAPES:raise ValueError('Select a valid object and shape label')
            try:b={k:float(r['bounds'][k]) for k in ('left','top','right','bottom')}
            except (KeyError,TypeError,ValueError):raise ValueError('Target needs a valid bounding box')
            if not all(math.isfinite(v) for v in b.values()) or not(0<=b['left']<b['right']<=detail['width'] and 0<=b['top']<b['bottom']<=detail['height']):raise ValueError('Target box must be inside the image')
            validated.append(dict(bounds={k:round(v,2) for k,v in b.items()},object=r['object'],shape='unresolved' if r['object']=='cloud' else r['shape']))
        if not validated and not body.get('no_object'):raise ValueError('Add a target or choose No object')
        review=dict(source='human',source_frame=detail['source_frame'],reviewed_at=utc(),regions=validated,
                    boxes_confirmed=bool(body.get('boxes_confirmed')),no_object=not bool(validated),note=str(body.get('note',''))[:1000])
        ready=bool(detail['clean_image'] and review['boxes_confirmed'] and all(r['object'] not in ('unknown','no_object','anomalous') for r in validated))
        self.records.mkdir(parents=True,exist_ok=True);self.images.mkdir(parents=True,exist_ok=True);self.references.mkdir(parents=True,exist_ok=True)
        clean=self.image(key,True);destination=self.images if detail['clean_image'] else self.references;snapshot=destination/(key+'.jpg')
        if not snapshot.exists():
            with tempfile.NamedTemporaryFile(dir=destination,delete=False) as tmp:
                temporary=Path(tmp.name)
                with clean.open('rb') as source:shutil.copyfileobj(source,tmp)
            temporary.replace(snapshot)
        record=dict(key=key,session_id=sid,event_id=eid,human_review=review,training_ready=ready,
                    image=snapshot.name,clean_image=detail['clean_image'],image_sha256=file_info(snapshot)['sha256'],width=detail['width'],height=detail['height'],
                    event_snapshot=event)
        with self.station.lock:
            # Store the durable training example independently of session cleanup.
            save(self.records/(key+'.json'),record)
            with (self.training/'review-history.jsonl').open('a') as log:log.write(json.dumps(dict(key=key,human_review=review))+'\n')
            current=load(folder/'motion-events.json',[])
            event=next((e for e in current if e.get('id')==eid),event)
            event['human_review']=review
            annotation=render_review(Image.open(snapshot),review,folder/f'motion-{eid}-boxed.jpg')
            event['annotation']=annotation;event['annotated_frame']=f'motion-{eid}-boxed.jpg'
            if not any(e.get('id')==eid for e in current):current.append(event)
            save(folder/'motion-events.json',current)
            m=load(folder/'manifest.json',{})
            for e in m.get('motion_events',[]):
                if e['id']==eid:e.update(human_review=review,annotation=annotation)
            m.setdefault('files',{})['motion-events.json']=file_info(folder/'motion-events.json')
            m['files'][event['annotated_frame']]=file_info(folder/event['annotated_frame'])
            for crop in annotation.get('detail_images',[]):
                for name in (crop['native_file'],crop['detail_file']):m['files'][name]=file_info(folder/name)
            if self.station.active and self.station.active['id']==sid:
                for e in self.station.active.get('motion_events',[]):
                    if e['id']==eid:e.update(human_review=review,annotation=annotation)
                self.station.active.setdefault('files',{}).update(m['files'])
            save(folder/'manifest.json',m)
            classifier=getattr(self.station,'classifier',None)
            if classifier:classifier.live_result=dict(detected_epoch=event.get('detected_epoch',0),regions=effective_classification(event)['regions'])
            from boxed_frames import copy_boxed,organize_classified
            copy_boxed(folder/event['annotated_frame'],boxed)
            organize_classified(self.collection,self.data)
            from anomalous_events import sync_anomalous
            sync_anomalous(self.data)
        return dict(state='saved',training_ready=ready,human_review=review)
    def export_training(self):
        """Export reviewed clean examples; split by session later, before training."""
        import zipfile
        output=io.BytesIO();classes=[c for c in OBJECTS if c not in ('unknown','no_object','cloud','anomalous')];included=0
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
            manifest=[]
            for p in sorted(self.records.glob('*.json')):
                r=load(p,{})
                if not r.get('training_ready'):continue
                image=self.images/r['image']
                if not image.is_file():continue
                lines=[]
                for region in r['human_review']['regions']:
                    if region['object']=='cloud':continue
                    b=region['bounds'];w=r['width'];h=r['height']
                    lines.append(f"{classes.index(region['object'])} {(b['left']+b['right'])/2/w:.8f} {(b['top']+b['bottom'])/2/h:.8f} {(b['right']-b['left'])/w:.8f} {(b['bottom']-b['top'])/h:.8f}")
                name=r['key'][:-4]
                archive.write(image,'images/'+name+'.jpg');archive.writestr('labels/'+name+'.txt','\n'.join(lines)+('\n' if lines else ''))
                manifest.append(dict(image=name+'.jpg',session_id=r['session_id'],event_id=r['event_id']));included+=1
            archive.writestr('classes.json',json.dumps(classes,indent=2));archive.writestr('examples.json',json.dumps(manifest,indent=2))
            archive.writestr('README.txt','Reviewed clean images and YOLO bounding boxes. Split by session_id from examples.json before training; adjacent video frames must stay in the same split. Model training is a separate step.\n')
        return output.getvalue()
