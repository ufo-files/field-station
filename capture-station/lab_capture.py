"""Confirmed lab-model events use the station's buffered video and RF capture."""
import hashlib,io,math,os,re,secrets,time
from pathlib import Path
from PIL import Image,ImageDraw
from experiments import load,save,utc
from motion_details import save_motion_details

class LabCapture:
    def __init__(self,station,preview):
        self.station=station;self.preview=preview;self.current=None;self.last_started=0
    def receive(self,body):
        version=str(body.get('model_id',''))
        if not re.fullmatch('[a-f0-9]{32}',version):raise ValueError('Invalid lab model version')
        matches=body.get('objects',[])
        if not isinstance(matches,list) or not 1<=len(matches)<=20:raise ValueError('Provide confirmed anomalous boxes')
        with self.station.lock:
            if time.time()-self.preview.stat().st_mtime>2:raise ValueError('No fresh camera frame')
            frame_epoch=float(body.get('frame_epoch',time.time()))
            if not math.isfinite(frame_epoch) or not 0<=time.time()-frame_epoch<10:raise ValueError('Model evidence frame is stale')
            snapshot=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'uap-lab-detection.jpg' if body.get('frame_sha256') else self.preview
            raw=snapshot.read_bytes()
            if body.get('frame_sha256') and hashlib.sha256(raw).hexdigest()!=body['frame_sha256']:raise ValueError('Model evidence frame changed')
            image=Image.open(io.BytesIO(raw)).convert('RGB');w,h=image.size
            if body.get('width')!=w or body.get('height')!=h:raise ValueError('Detection dimensions do not match the live frame')
            regions=[]
            for match in matches:
                score=float(match.get('score',0));x,y,bw,bh=map(float,match['box'])
                detail_score=float(match.get('detail_score',0))
                if not math.isfinite(detail_score) or detail_score<.55:raise ValueError('Model match lacks verified object detail; diffuse cloud matches cannot trigger capture')
                if match.get('label')!='anomalous' or not all(math.isfinite(v) for v in (score,x,y,bw,bh)) or not .9<=score<=1.00001 or min(x,y)<0 or min(bw,bh)<3 or x+bw>w or y+bh>h:raise ValueError('Invalid anomalous match')
                bounds=dict(left=int(x),top=int(y),right=min(w,math.ceil(x+bw)),bottom=min(h,math.ceil(y+bh)))
                regions.append(dict(bounds=bounds,source_frame='after',object=dict(label='anomalous',source='uap-lab',confidence=score,detail_score=detail_score,model_version=version,target_id=match.get('target_id')),shape=dict(label='unresolved')))
            now=time.time();active=self.station.active
            current=self.current if self.current and active and self.current['session_id']==active['id'] and self.current['model_id']==version else None
            if current is None and now-self.last_started<90:return dict(state='cooldown',cooldown_until=self.last_started+90)
            self.station.motion_trigger.last_motion_epoch=now
            if current is None:
                event=dict(id=secrets.token_hex(8),detected_at=utc(),detected_epoch=frame_epoch,motion_started_epoch=frame_epoch,
                    algorithm='uap-lab-appearance-v1',model_version=version,changed_area_percent=0,settings=self.station.motion_trigger.config.copy(),
                    classification=dict(state='completed',source='uap-lab',model_version=version,regions=regions))
                if not active:
                    if not self.station.experiments.pause_exports():raise ValueError('Waiting for frame exports to pause')
                    try:self.station.start(dict(title='Model anomaly · '+utc(),condition='silence',minutes=1),motion_event=event)
                    except Exception:self.station.experiments.resume_exports();raise
                    active=self.station.active;active['capture_origin']='lab_model'
                folder=self.station.data_path(active['id']);event['session_id']=active['id'];eid=event['id']
                for suffix in ('before','after'):(folder/f'motion-{eid}-{suffix}.jpg').write_bytes(raw)
                boxed=folder/f'motion-{eid}-boxed.jpg';painted=image.copy();draw=ImageDraw.Draw(painted)
                boxes=[]
                for r in regions:
                    b=r['bounds'];draw.rectangle(tuple(b[k] for k in ('left','top','right','bottom')),outline='#ffcf33',width=3);draw.text((b['left'],max(0,b['top']-20)),'Anomalous | model '+version[:8],fill='#ffcf33',stroke_width=1,stroke_fill='black');boxes.append(dict(**b,label='Anomalous | model',visible_in='after'))
                painted.save(boxed,quality=95)
                event['annotation']=dict(boxes=boxes,source_frame='after',frame_width=w,frame_height=h,detail_images=save_motion_details(image,boxes,boxed,'after'))
                event['annotated_frame']=boxed.name;event['evidence_files']=[f'motion-{eid}-before.jpg',f'motion-{eid}-after.jpg'];event['action']='started_recording' if active.get('capture_origin')=='lab_model' else 'annotated_existing_recording'
                events=load(folder/'motion-events.json',[]);events.append(event);save(folder/'motion-events.json',events)
                active.setdefault('motion_events',[]).append(event);active.setdefault('lab_model_events',[]).append(dict(event_id=eid,model_id=version,detected_epoch=now))
                active['markers'].append(dict(timestamp=utc(),elapsed_seconds=now-active['started_epoch'],note='Confirmed lab-model anomalous match; model '+version))
                current=self.current=dict(session_id=active['id'],event_id=eid,model_id=version,target_ids=[]);self.last_started=now
            folder=self.station.data_path(active['id']);frames=folder/'model-frames';frames.mkdir(exist_ok=True)
            name=f'{current["event_id"]}-{time.time_ns()}.jpg';(frames/name).write_bytes(raw)
            with (frames/'detections.jsonl').open('a') as f:
                import json
                f.write(json.dumps(dict(frame=name,timestamp=now,model_id=version,regions=regions))+'\n')
            ids={r['object'].get('target_id') or i+1 for i,r in enumerate(regions)}
            current['target_ids']=sorted(set(current.get('target_ids',[]))|ids)
            current['target_count']=len(current['target_ids'])
            for entry in active.get('lab_model_events',[]):
                if entry['event_id']==current['event_id']:entry['target_ids']=current['target_ids']
            save(folder/'manifest.json',active)
            return dict(state='recording',**current,rf_log='rf.jsonl',frames='model-frames',video='video.mkv')
