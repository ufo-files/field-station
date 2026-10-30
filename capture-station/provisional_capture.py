"""Capture-first provisional evidence. Never asserts model confirmation."""
import json,math,re,time
from experiments import load,save,utc

class ProvisionalCapture:
    def __init__(self,station):self.station=station
    def receive(self,body):
        stamp=float(body['frame_epoch']);sequence=int(body['sequence']);generation=str(body['generation'])
        if not math.isfinite(stamp) or not 0<=time.time()-stamp<15:raise ValueError('Provisional evidence is stale')
        if sequence<0 or not re.fullmatch(r'run-[a-f0-9]+',generation):raise ValueError('Invalid native frame identity')
        boxes=body.get('boxes',[])
        if not boxes and not body.get('global_change'):raise ValueError('No motion candidate')
        if not isinstance(boxes,list) or len(boxes)>128:raise ValueError('Invalid candidate summary')
        for box in boxes:
            if len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):raise ValueError('Invalid candidate box')
            x,y,w,h=box
            if min(x,y)<0 or min(w,h)<=0 or x+w>1920 or y+h>1080:raise ValueError('Candidate outside native frame')
        with self.station.lock:
            active=self.station.active
            # Idempotence prevents duplicate sessions when an HTTP response is lost.
            key=f'{generation}:{sequence}'
            if active and key==active.get('last_provisional_key'):return dict(state='recording',session_id=active['id'])
            onset=float(body.get('onset_epoch',stamp))
            if not math.isfinite(onset) or not stamp-2<=onset<=stamp:raise ValueError('Invalid motion onset')
            self.station.motion_trigger.last_motion_epoch=stamp
            if active is None:
                event=dict(detected_epoch=stamp,motion_started_epoch=onset)
                if not self.station.experiments.pause_exports():raise ValueError('Waiting for frame exports')
                try:self.station.start(dict(title='Provisional motion · '+utc(),condition='control',minutes=1,notes='Unclassified native-frame motion candidate. Not a confirmed anomaly.'),motion_event=event)
                except Exception:self.station.experiments.resume_exports();raise
                active=self.station.active
                active.update(capture_origin='provisional_motion',classification_state='pending',provisional=True)
                active['duration_limit_seconds']=60
            folder=self.station.data_path(active['id'])
            active['last_provisional_key']=key
            active['provisional_last_seen_epoch']=stamp
            save(folder/'manifest.json',active)
            job=load(folder/'provisional.json',None)
            if job is None:
                job=dict(schema_version=1,session_id=active['id'],created=time.time(),state='capturing',classification='unclassified',model_id=body.get('model_id'),automatic_deletion=False)
                save(folder/'provisional.json',job)
            with (folder/'provisional-candidates.jsonl').open('a') as out:
                out.write(json.dumps(dict(frame_epoch=stamp,sequence=sequence,generation=generation,boxes=boxes,global_change=bool(body.get('global_change')),candidate_count=body.get('candidate_count',len(boxes)),kind='provisional_motion'))+'\n')
            return dict(state='recording',session_id=active['id'],classification='unclassified')
    def manual(self,body):
        with self.station.lock:
            active=self.station.active
            if not active or active['id']!=body.get('session_id'):raise ValueError('Session changed; refresh before starting manual recording')
            if active.get('capture_origin')!='provisional_motion':raise ValueError('Session is already controlled by another recording mode')
            active.update(capture_origin='manual',duration_limit_seconds=7200,title='Manual recording · continued from provisional capture')
            active.pop('capture_mode',None)
            save(self.station.data_path(active['id'])/'manifest.json',active)
            return dict(id=active['id'])
