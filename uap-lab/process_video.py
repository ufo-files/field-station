#!/usr/bin/env python3
"""Automation entry point: process_video.py VIDEO [--model VERSION] [--rf-log RF.jsonl]."""
import argparse,hashlib,os,time,uuid
from pathlib import Path
import lab

def process(path,model_id=None,rf_log=None):
    path=Path(path).resolve()
    model=lab.read(lab.DATA/'models'/lab.checked_id(model_id)/'model.json') if model_id else lab.read(lab.DATA/'active-model.json')
    if not model:raise ValueError('Save a model in the browser first')
    if 'anomalous' not in model['classes']:raise ValueError('The saved model needs anomalous target examples')
    meta=lab.probe(path);vid=uuid.uuid4().hex;folder=lab.video_path(vid);folder.mkdir();lab.space_check(path.stat().st_size)
    # An immutable copy protects the job from changes to an upstream intake file.
    lab.shutil.copyfile(path,folder/'source');meta.update(id=vid,name=path.name,created=time.time(),provenance=dict(collection='automated-intake',local_file=str(path)))
    lab.save(folder/'video.json',meta);lab.save(folder/'review.json',dict(completed=True,automated_intake=True))
    rid=uuid.uuid4().hex;run=lab.DATA/'runs'/rid;run.mkdir();lab.save(run/'model.json',model)
    if rf_log:lab.shutil.copyfile(rf_log,run/'source-rf.jsonl')
    lab.evaluate(rid,vid,model,.97,['anomalous'])
    result=lab.read(run/'run.json')
    if result['state']!='complete':raise ValueError(result.get('error','Processing failed'))
    return run
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('video');p.add_argument('--model');p.add_argument('--rf-log');a=p.parse_args();print(process(a.video,a.model,a.rf_log))
