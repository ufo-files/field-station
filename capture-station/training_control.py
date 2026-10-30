"""Shared status/configuration for the separate training service."""
from pathlib import Path
import time
from experiments import load,save
from training_data import review_inventory

BUSY={'queued','building_dataset','uploading','initializing','extracting_features','training','exporting','calibrating','evaluating','candidate_ready','deploying'}
DEFAULTS=dict(auto_enabled=True,min_new_reviews=10,min_interval_seconds=1800)


class TrainingControl:
    def __init__(self,root,data):
        self.root=Path(root);self.run=self.root/'run';self.training=Path(data).resolve().parent/'training'
        self.path=self.run/'model-training.json';self.config_path=self.run/'model-training-config.json'
        self.request_path=self.run/'model-training-request.json'
    def config(self):return dict(DEFAULTS,**load(self.config_path,{}))
    def status(self):
        state=load(self.path,dict(phase='idle',message='Training service is starting'))
        inventory=review_inventory(self.training);previous=load(self.run/'model-training-last-data.json',{})
        changes=sum(previous.get(k)!=v['signature'] for k,v in inventory['records'].items())+len(set(previous)-set(inventory['records']))
        state=dict(state,active_model=load(self.run/'active-model.json',dict(version='baseline-yolov3',name='Original YOLO detector')),
                   configuration=self.config(),confirmed_reviews=len(inventory['records']),class_counts=inventory['counts'],
                   class_sessions={k:len(v) for k,v in inventory['sessions'].items()},new_reviews=changes,
                   busy=state.get('phase') in BUSY,request_pending=self.request_path.exists())
        return state
    def start(self,body=None):
        state=self.status()
        if state['busy']:return state
        save(self.request_path,dict(requested_epoch=time.time(),source='web'))
        return dict(state,phase='queued',busy=True,request_pending=True,message='Training requested')
    def configure(self,body):
        config=self.config()
        if 'auto_enabled' in body:config['auto_enabled']=bool(body['auto_enabled'])
        save(self.config_path,config)
        return self.status()
