"""Every-observation temporal features from explicit measured native frames."""
import json,math
from pathlib import Path
import numpy as np
from temporal_model import FEATURES
from temporal_features_fast import feature_window

class TemporalRuntime:
    def __init__(self,path):
        self.path=Path(path);self.signature=None;self.model_id=None;self.bank=None;self.labels=[];self.scale=None;self.state='needs_temporal_annotations';self.error=None
    def refresh(self):
        try:
            stat=self.path.stat();signature=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
            if signature==self.signature:return
            value=json.loads(self.path.read_text());model=value.get('temporal',{});self.model_id=value.get('id');self.bank=None;self.labels=[];self.scale=None;self.state=model.get('state','needs_temporal_annotations')
            if model.get('state')=='trained':
                if model.get('feature_names')!=FEATURES:raise ValueError('Temporal feature schema mismatch')
                bank=np.asarray([s['features'] for s in model['samples']],dtype=np.float64);scale=np.asarray(model['scale'],dtype=np.float64)
                if bank.ndim!=2 or bank.shape[1]!=len(FEATURES) or len(bank)==0 or scale.shape!=(len(FEATURES),) or not np.isfinite(bank).all() or not np.isfinite(scale).all() or np.any(scale<=0):raise ValueError('Invalid temporal model parameters')
                self.bank=bank/scale;self.scale=scale;self.labels=[s['label'] for s in model['samples']]
            self.signature=signature;self.error=None
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.bank=None;self.state='unavailable';self.error=str(exc)
    def vector(self,observation,track,pts,width,height):
        x,y,w,h=observation['box'];point=dict(time=pts,bounds=dict(x=x/width,y=y/height,w=w/width,h=h/height),shape_descriptor=observation['shape_descriptor'])
        history=track.get('temporal_history',[])
        if history and pts<=history[-1]['time']:raise ValueError('Temporal observations must increase')
        history=[*history,point][-3:];track['temporal_history']=history
        if len(history)<3 or self.bank is None:return None
        return np.asarray(feature_window(history),dtype=np.float64)/self.scale
    def result(self,track,distances):
        history=track['temporal_history'];index=int(np.argmin(distances));distance=float(distances[index])
        return dict(model_id=self.model_id,nearest_label=self.labels[index],distance=distance,observations=3,first_pts=history[0]['time'],last_pts=history[-1]['time'],role='uncalibrated_motion_similarity',capture_control=False)
    def observe(self,observation,track,pts,width,height):
        vector=self.vector(observation,track,pts,width,height)
        if vector is None:return None
        distances=np.mean((self.bank-vector)**2,axis=1);index=int(np.argmin(distances));distance=float(distances[index])
        return self.result(track,distances)
    def observe_many(self,observations,tracks,pts,width,height):
        selected=[];vectors=[]
        for observation in observations:
            track=tracks[observation['proposed_track_id']]
            vector=self.vector(observation,track,pts,width,height)
            if vector is not None:selected.append((observation,track));vectors.append(vector)
        # Bound intermediate memory while preserving every observation and window.
        for start in range(0,len(vectors),128):
            batch=np.asarray(vectors[start:start+128])
            distances=np.mean((self.bank[None,:,:]-batch[:,None,:])**2,axis=2)
            for (observation,track),row in zip(selected[start:start+128],distances):
                observation['temporal']=self.result(track,row)
    def status(self):return dict(state=self.state,model_id=self.model_id,windows=len(self.labels),error=self.error,capture_control=False)
