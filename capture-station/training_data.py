"""Reviewed native target crops, immutable run snapshots, and session-isolated splits."""
import base64
from collections import Counter,defaultdict
import hashlib
import io
import json
from pathlib import Path
import tarfile
from PIL import Image
from experiments import load,save
from object_analysis import crop_for_model

TRAINABLE={'bird','airplane','cloud','insect','other_animal','balloon','star','satellite','shooting_star','house','antenna','vehicle','drone','tree'}


def review_inventory(training):
    records={};counts=Counter();sessions=defaultdict(set)
    training=Path(training)
    for p in sorted((training/'reviews').glob('*.json')):
        r=load(p,{})
        if not r.get('training_ready') or not r.get('clean_image',True):continue
        if not (training/'images'/r.get('image','')).is_file():continue
        labels={b.get('object') for b in r.get('human_review',{}).get('regions',[])}
        if labels-TRAINABLE:continue
        supervision=dict(source_frame=r['human_review'].get('source_frame'),
            regions=[dict(bounds=v['bounds'],object=v['object']) for v in r['human_review'].get('regions',[])])
        signature=hashlib.sha256(json.dumps(dict(image=r.get('image_sha256'),review=supervision),sort_keys=True).encode()).hexdigest()
        records[r['key']]=dict(record=r,signature=signature)
        for region in r.get('human_review',{}).get('regions',[]):
            label=region['object'];counts[label]+=1;sessions[label].add(r['session_id'])
    return dict(records=records,counts=dict(counts),sessions={k:sorted(v) for k,v in sessions.items()})


def session_splits(session_labels,previous=None):
    assignments=dict(previous or {});labels=defaultdict(set)
    for sid,classes in session_labels.items():
        for label in classes:labels[label].add(sid)
    for label,groups in sorted(labels.items(),key=lambda item:len(item[1])):
        target=max(2,round(len(groups)*.2))
        for role in ('test','calibration'):
            have=sum(assignments.get(sid)==role for sid in groups)
            candidates=sorted((sid for sid in groups if sid not in assignments),key=lambda sid:hashlib.sha256((label+sid).encode()).hexdigest())
            for sid in candidates:
                if have>=target:break
                # Every class sharing a session must retain at least two potential training sessions.
                if any(sum(assignments.get(x,'train')=='train' for x in labels[c])<=2 for c in session_labels[sid]):continue
                assignments[sid]=role;have+=1
    for sid in session_labels:assignments.setdefault(sid,'train')
    problems=[]
    for label,groups in labels.items():
        counts=Counter(assignments[sid] for sid in groups)
        for role in ('train','calibration','test'):
            if counts[role]<2:problems.append(f'{label}: needs two separate {role} recording sessions (has {counts[role]})')
    if problems:raise ValueError('; '.join(problems))
    return assignments


def build_dataset(training,data,run_dir,ledger_path):
    training=Path(training);data=Path(data);run_dir=Path(run_dir);run_dir.mkdir(parents=True,exist_ok=True)
    inventory=review_inventory(training)
    eligible={label for label,groups in inventory['sessions'].items() if len(groups)>=6}
    if not {'bird','airplane'}<=eligible:raise ValueError('Need at least six distinct recording sessions each for reviewed birds and airplanes')
    samples=[];session_labels=defaultdict(set)
    for key,item in inventory['records'].items():
        r=item['record']
        for i,region in enumerate(r['human_review']['regions']):
            label=region['object']
            if label not in eligible:continue
            session_labels[r['session_id']].add(label)
            samples.append(dict(key=key,session_id=r['session_id'],label=label,region=region,index=i,record=r))
    assignments=session_splits(session_labels,load(ledger_path,{}))
    save(ledger_path,assignments)
    images=run_dir/'images';images.mkdir(exist_ok=True);rows=[]
    for number,s in enumerate(samples):
        r=s['record'];bounds=s['region']['bounds'];image_path=training/'images'/r['image']
        source=r['human_review']['source_frame'];eid=r['event_id'];folder=data/r['session_id']
        image=Image.open(image_path).convert('RGB');stem=f'{number:05d}'
        source_name=f'images/{stem}-source.jpg';(run_dir/source_name).write_bytes(base64.b64decode(crop_for_model(image,bounds)))
        pair=[]
        for suffix in ('before','after'):
            original=folder/f'motion-{eid}-{suffix}.jpg'
            if suffix==source:pair.append(source_name)
            elif original.is_file():
                name=f'images/{stem}-{suffix}.jpg'
                with Image.open(original) as im:(run_dir/name).write_bytes(base64.b64decode(crop_for_model(im.convert('RGB'),bounds)))
                pair.append(name)
            else:pair.append(None)
        rows.append(dict(id=stem,image=source_name,pair=pair,source_index=0 if source=='before' else 1,
                         label=s['label'],session_id=s['session_id'],split=assignments[s['session_id']],
                         native_size=max(bounds['right']-bounds['left'],bounds['bottom']-bounds['top'])))
    signatures={k:v['signature'] for k,v in inventory['records'].items()}
    fingerprint=hashlib.sha256(json.dumps(signatures,sort_keys=True).encode()).hexdigest()
    manifest=dict(schema=1,classes=sorted(eligible),samples=rows,fingerprint=fingerprint,review_signatures=signatures,
                  counts=inventory['counts'],split_counts=dict(Counter(s['split'] for s in rows)),
                  session_counts={role:len({s['session_id'] for s in rows if s['split']==role}) for role in ('train','calibration','test')},
                  method='Native clean crops; unchanged session assignment across runs; no smoothed images')
    save(run_dir/'dataset.json',manifest)
    bundle=run_dir/'dataset.tar.gz'
    with tarfile.open(bundle,'w:gz') as archive:
        archive.add(run_dir/'dataset.json',arcname='dataset.json')
        archive.add(images,arcname='images')
    return manifest,bundle
