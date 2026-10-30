"""Timestamp-based event windows over immutable native spool segments.

No wall-clock expiry: slow analysis creates a backlog, never a missed recording.
"""
import hashlib,json,os,time
from pathlib import Path
from datetime import datetime,timezone

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
    with tmp.open('w') as out:json.dump(value,out);out.flush();os.fsync(out.fileno())
    tmp.replace(path)

class SpoolEvents:
    def __init__(self,root):self.root=Path(root);self.run=None;self.event=None;self.last_save=0
    def update(self,timing,boxes,metrics,generation,model_id):
        folder=self.root/generation
        if generation!=self.run:
            if self.event:self.finish(interrupted=True)
            self.run=generation
            path=folder/'open-event.json'
            self.event=json.loads(path.read_text()) if path.exists() else None
        pts=timing['pts_seconds'];candidate=bool(boxes or metrics.get('global_change'))
        if self.event and pts>=self.event['end_pts']:self.finish(reason='post_roll_complete')
        elif self.event and pts-self.event['start_pts']>=50:self.finish(reason='window_limit')
        if self.event and candidate and timing['sequence']<=self.event.get('last_sequence',-1):candidate=False
        if candidate:
            if self.event is None:
                sid=datetime.fromtimestamp(timing['received_epoch'],timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+hashlib.sha256(f'{generation}:{timing["sequence"]}'.encode()).hexdigest()[:6]
                self.event=dict(session_id=sid,generation=generation,first_sequence=timing['sequence'],onset_pts=pts,start_pts=max(0,pts-10),end_pts=pts+10,created=time.time(),frame_epoch=timing['received_epoch'],model_id=model_id,state='open',kind='provisional_motion')
            self.event.update(last_sequence=timing['sequence'],last_seen_pts=pts,end_pts=min(pts+10,self.event['start_pts']+60))
            journal=folder/'candidates'/ (self.event['session_id']+'.jsonl');journal.parent.mkdir(exist_ok=True)
            with journal.open('a') as log:log.write(json.dumps(dict(sequence=timing['sequence'],pts_seconds=pts,frame_epoch=timing['received_epoch'],boxes=boxes,global_change=metrics.get('global_change',False)))+'\n')
        if self.event and (time.monotonic()-self.last_save>=1 or candidate and self.event['first_sequence']==timing['sequence']):
            atomic(folder/'open-event.json',self.event);self.last_save=time.monotonic()
    def finish(self,interrupted=False,reason=None):
        if not self.event:return
        folder=self.root/self.event['generation'];event=dict(self.event,state='ready',interrupted=interrupted,finish_reason=reason or ('capture_interrupted' if interrupted else 'post_roll_complete'))
        atomic(folder/'events'/(event['session_id']+'.json'),event)
        (folder/'open-event.json').unlink(missing_ok=True);self.event=None
    def acknowledge(self,generation,state):
        folder=self.root/generation
        if self.event:
            atomic(folder/'open-event.json',self.event)
            journal=folder/'candidates'/(self.event['session_id']+'.jsonl')
            if journal.exists():
                with journal.open('rb') as source:os.fsync(source.fileno())
        # The pending event window is durable before acknowledging its input frames.
        atomic(folder/'analysis-ack.json',dict(generation=generation,last_sequence=state['last_sequence'],last_pts_seconds=state['last_pts_seconds'],acknowledged_epoch=time.time(),stage='motion_analysis',integrity_ok=state.get('generation_missing_frames',0)==0,coverage_start_sequence=state.get('coverage_start_sequence'),intentionally_discarded_ranges=state.get('intentionally_discarded_ranges',[])))
