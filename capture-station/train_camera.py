#!/usr/bin/env python3
"""Pi-owned training scheduler; remote training cannot deploy without this controller."""
import fcntl
import hashlib
import json
from pathlib import Path
import queue
import re
import shlex
import signal
import subprocess
import threading
import time
from datetime import datetime,timezone
import secrets
from experiments import load,save,utc
from m1_encode import ssh_args
from training_control import TrainingControl,BUSY
from training_data import review_inventory,build_dataset

ROOT=Path(__file__).resolve().parent


class TrainingController:
    def __init__(self,root=ROOT,data=None):
        self.root=Path(root);self.data=Path(data or self.root/'sessions').resolve();self.control=TrainingControl(self.root,self.data)
        self.stop=threading.Event();self.process=None;self.config=load(self.root/'private/m1/config.json',{})
        self.remote_root=Path(self.config['worker']).parent
    def state(self,phase,**values):
        old=load(self.control.path,{})
        old.update(values);old.update(phase=phase,updated_epoch=time.time());save(self.control.path,old)
    def remote(self,command,input=None,timeout=120):
        r=subprocess.run(ssh_args(self.config)+[command],input=input,capture_output=True,timeout=timeout)
        if r.returncode:raise OSError('Mac worker request failed: '+r.stderr.decode(errors='replace')[-400:])
        return r.stdout
    def get_policy(self):
        path=str(self.remote_root/'active-model.json')
        code='import pathlib; p=pathlib.Path('+repr(path)+'); print(p.read_text() if p.exists() else "null")'
        return json.loads(self.remote('/usr/bin/python3 -c '+shlex.quote(code)))
    def put_policy(self,policy):
        path=str(self.remote_root/'active-model.json')
        code='import sys,json,pathlib; p=pathlib.Path('+repr(path)+'); v=json.load(sys.stdin); t=p.with_suffix(".new"); t.write_text(json.dumps(v)) if v is not None else None; t.replace(p) if v is not None else p.unlink(missing_ok=True)'
        self.remote('/usr/bin/python3 -c '+shlex.quote(code),json.dumps(policy).encode())
    def deploy(self,run_id,report,local):
        if not report.get('passed'):raise ValueError('Candidate did not pass evaluation')
        self.state('deploying',progress=97,message='Activating the validated model')
        policy=dict(version=run_id,compiled_path=str(self.remote_root/'training-runs'/run_id/'camera.mlmodelc'),
            thresholds=report['thresholds'],minimum_native_size=report['minimum_native_size'],kind='camera-crop-mobilenet-v3')
        previous=self.get_policy();save(local/'previous-model.json',previous)
        self.put_policy(policy)
        try:
            dataset=load(local/'dataset.json');passing={t['id'] for t in report['tests'] if t['candidate'] in ('bird','airplane') and t['candidate']==t['truth'] and t['candidate']!=t['baseline']}
            test=next(s for s in dataset['samples'] if s['id'] in passing)
            import base64
            payload=dict(images=[base64.b64encode((local/test['image']).read_bytes()).decode()])
            response=json.loads(self.remote(shlex.quote(str(self.remote_root/'vision_worker')),json.dumps(payload).encode()))
            if response.get('model_version')!=run_id or response.get('model_error'):raise ValueError('Active model verification failed')
            if not any(label.get('source')=='camera-trained' for result in response['results'] for label in result['labels']):raise ValueError('Active classifier did not reproduce its held-out prediction')
        except Exception:
            self.put_policy(previous);raise
        metadata=dict(policy,name='Camera-trained classifier',deployed_at=utc(),report=report,previous_version=previous.get('version') if previous else 'baseline-yolov3')
        save(self.root/'run/active-model.json',metadata)
        return metadata
    def run_once(self):
        run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)
        local=self.control.training/'runs'/run_id;local.mkdir(parents=True,exist_ok=True)
        save(self.root/'run/model-training-last-attempt.json',dict(epoch=time.time(),run_id=run_id))
        self.state('building_dataset',run_id=run_id,progress=1,message='Preparing confirmed clean examples',error=None,report=None)
        try:
            dataset,bundle=build_dataset(self.control.training,self.data,local,self.control.training/'session-splits.json')
            save(self.root/'run/model-training-last-data.json',dataset['review_signatures'])
            self.state('uploading',progress=2,message='Sending small target crops to the Mac',dataset_counts=dataset['counts'],split_counts=dataset['split_counts'])
            executable=str(self.remote_root/'training-venv/bin/python');worker=str(self.remote_root/'train_camera_worker.py')
            command=' '.join(map(shlex.quote,[executable,worker,'--run',run_id,'--receive','--sha256',hashlib.sha256(bundle.read_bytes()).hexdigest()]))
            self.remote(command,bundle.read_bytes(),timeout=120)
            command=' '.join(map(shlex.quote,[executable,worker,'--run',run_id]))
            updates=queue.Queue()
            with (local/'worker.log').open('wb') as log:
                self.process=subprocess.Popen(ssh_args(self.config)+[command],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=log)
                proc=self.process
                def read_output():
                    for line in iter(proc.stdout.readline,b''):updates.put(line)
                    updates.put(None)
                threading.Thread(target=read_output,daemon=True).start()
                ended=False;began=time.monotonic();heartbeat=0
                while not ended or proc.poll() is None:
                    if self.stop.is_set():raise OSError('Training controller stopped; active model unchanged')
                    if time.monotonic()-began>3600:raise OSError('Training run exceeded one hour')
                    try:line=updates.get(timeout=1)
                    except queue.Empty:line=b''
                    if line is None:ended=True
                    elif line:
                        try:
                            update=json.loads(line)
                            if isinstance(update,dict) and 'phase' in update:
                                phase=update.pop('phase');self.state(phase,run_id=run_id,**update)
                        except (ValueError,TypeError):pass
                    if time.monotonic()-heartbeat>15:
                        heartbeat=time.monotonic();current=load(self.control.path,{});self.state(current.get('phase','training'))
                if proc.wait():raise OSError('Mac training failed; see training run log')
            report=load(self.control.path,{}).get('report')
            if not report:
                path=self.remote_root/'training-runs'/run_id/'evaluation.json'
                report=json.loads(self.remote('cat '+shlex.quote(str(path))))
            save(local/'evaluation.json',report)
            if report['passed']:
                active=self.deploy(run_id,report,local)
                self.state('deployed',progress=100,finished_at=utc(),message='Camera-trained model is active',report=report,active_version=active['version'])
            else:self.state('rejected',progress=100,finished_at=utc(),message='Candidate kept for review; current model unchanged',report=report,error='; '.join(report['reasons']))
        except ValueError as error:
            phase='waiting_for_data' if load(self.control.path,{}).get('phase')=='building_dataset' else 'failed'
            self.state(phase,progress=0,message=str(error),error=str(error))
        except Exception as error:
            self.state('failed',progress=0,message='Training did not change the active model',error=str(error))
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.process=None
    def daemon(self):
        self.root.joinpath('run').mkdir(exist_ok=True)
        with (self.root/'run/model-training.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            old=load(self.control.path,{})
            if old.get('phase') in BUSY:self.state('failed',progress=0,error='Previous training controller interrupted; start another run to retry',message='Active model unchanged')
            elif not old:self.state('idle',progress=0,message='Ready to learn from confirmed reviews')
            while not self.stop.is_set():
                try:
                    requested=self.control.request_path.exists()
                    if requested:self.control.request_path.unlink(missing_ok=True)
                    config=self.control.config();inventory=review_inventory(self.control.training);old=load(self.root/'run/model-training-last-data.json',{})
                    changes=sum(old.get(k)!=v['signature'] for k,v in inventory['records'].items())+len(set(old)-set(inventory['records']))
                    last=load(self.root/'run/model-training-last-attempt.json',{}).get('epoch',0)
                    automatic=config['auto_enabled'] and changes>=config['min_new_reviews'] and time.time()-last>=config['min_interval_seconds']
                    if requested or automatic:self.run_once()
                except Exception as error:self.state('failed',error=str(error),message='Training controller is waiting to retry')
                self.stop.wait(5)


def main():
    controller=TrainingController()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:controller.stop.set())
    controller.daemon()

if __name__=='__main__':main()
