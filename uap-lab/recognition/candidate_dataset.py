"""Immutable crop-training snapshots; recording groups and exact pixels cannot cross splits."""
import argparse,hashlib,json,shutil,time
from collections import Counter,defaultdict
from pathlib import Path
from PIL import Image

LABELS={'anomalous','airplane','bird','insect','cloud','tree','other_animal','balloon','drone','unknown'}
def read(path,default=None):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return default

def group_rows(rows):
    parent={r['group']:r['group'] for r in rows}
    def find(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    by_source={}
    for row in rows:
        sha=row.get('source_sha256')
        if sha:
            if sha in by_source:parent[find(row['group'])]=find(by_source[sha])
            else:by_source[sha]=row['group']
    by_pixel=defaultdict(list)
    for row in rows:by_pixel[row['pixel_sha256']].append(row)
    for copies in by_pixel.values():
        first=find(copies[0]['group'])
        for row in copies[1:]:parent[find(row['group'])]=first
    components=defaultdict(list)
    for row in rows:components[find(row['group'])].append(row)
    conflicting_pixels={key for key,copies in by_pixel.items() if len({r['label'] for r in copies})>1}
    kept=[];quarantine=[]
    for members in components.values():
        aliases=sorted({r['group'] for r in members});group=hashlib.sha256('\n'.join(aliases).encode()).hexdigest()
        fixed={r['fixed_split'] for r in members if r.get('fixed_split')}
        conflicts=any(r['pixel_sha256'] in conflicting_pixels for r in members)
        reason='conflicting_labels_for_identical_pixels' if conflicts else 'duplicate_pixels_across_frozen_splits' if len(fixed)>1 else None
        if reason:
            quarantine.extend(dict(origin=r['origin'],reason=reason) for r in members);continue
        seen=set()
        for row in members:
            if row['pixel_sha256'] in seen:continue
            seen.add(row['pixel_sha256']);kept.append(dict(row,group=group,group_aliases=aliases,fixed_split=next(iter(fixed),None)))
    return kept,quarantine

def assign_splits(rows):
    labels=defaultdict(set);group_labels=defaultdict(set);assigned={}
    for r in rows:
        labels[r['label']].add(r['group']);group_labels[r['group']].add(r['label'])
        if r.get('fixed_split'):
            if r['fixed_split'] not in ['train','calibration','test']:raise ValueError('Invalid frozen split')
            assigned[r['group']]=r['fixed_split']
    for label,groups in sorted(labels.items(),key=lambda p:len(p[1])):
        target=max(2,round(len(groups)*.2))
        for role in ['calibration','test']:
            have=sum(assigned.get(g)==role for g in groups)
            for g in sorted(groups,key=lambda g:hashlib.sha256((label+g).encode()).hexdigest()):
                if have>=target:break
                if g in assigned:continue
                if any(sum(assigned.get(x,'train')=='train' for x in labels[c])<=2 for c in group_labels[g]):continue
                assigned[g]=role;have+=1
    for g in group_labels:assigned.setdefault(g,'train')
    for r in rows:r['split']=assigned[r['group']]
    coverage={label:{role:len({r['group'] for r in rows if r['label']==label and r['split']==role}) for role in ['train','calibration','test']} for label in sorted(labels)}
    blockers=[f'{label}: fewer than two independent {role} groups' for label,v in coverage.items() for role,n in v.items() if n<2]
    return coverage,blockers

def load_rows(lab_root,legacy):
    rows=[];excluded=[];omitted=read(lab_root/'omitted-videos.json',{});omitted_sessions=set()
    def add(path,label,group,origin,fixed=None,annotation=None,source_sha256=None):
        if label not in LABELS:excluded.append(dict(origin=origin,reason='unsupported_label'));return
        try:
            with Image.open(path) as source:im=source.convert('RGB');w,h=im.size;digest=hashlib.sha256(f'{w}x{h}:RGB:'.encode()+im.tobytes()).hexdigest()
            if min(w,h)<3:raise ValueError('Target smaller than three pixels')
        except (OSError,ValueError) as exc:excluded.append(dict(origin=origin,reason='invalid_crop',detail=str(exc)));return
        rows.append(dict(source=str(path),label=label,group=group,origin=origin,fixed_split=fixed,pixel_sha256=digest,native_width=w,native_height=h,annotation=annotation,source_sha256=source_sha256))
    for folder in sorted((lab_root/'videos').iterdir()):
        if not folder.is_dir():continue
        meta=read(folder/'video.json',{});sha=meta.get('sha256');provenance=meta.get('provenance',{});sid=provenance.get('session_id')
        if sha in omitted or read(folder/'training-excluded.json',{}).get('excluded'):
            if sid:omitted_sessions.add(sid)
            excluded.append(dict(origin='lab:'+folder.name,reason='user_excluded'));continue
        annotations=read(folder/'annotations.json',[])
        if not annotations:continue
        if not sha:excluded.append(dict(origin='lab:'+folder.name,reason='missing_source_sha'));continue
        session=read(lab_root.parent/'sessions'/str(sid)/'manifest.json',{}) if sid else {}
        group='generation:'+session['spool_generation'] if session.get('spool_generation') else 'session:'+sid if sid else 'sha:'+sha
        for a in annotations:
            name=a.get('image','');path=folder/name
            if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe annotation image path')
            add(path,a['label'],group,'lab:'+folder.name+':'+a['id'],annotation={k:a.get(k) for k in ['id','time','frame_index','track_id','bounds','shape_descriptor']},source_sha256=sha)
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from email_training import reviewed_examples
    for reviewed in reviewed_examples(lab_root):
        add(reviewed['image'],reviewed['label'],reviewed['group'],'email:'+reviewed['id'],annotation=dict(id=reviewed['id'],source='explicit_email_review'))
    legacy_data=read(legacy/'dataset.json',{})
    if not legacy_data.get('review_signatures'):raise ValueError('Legacy snapshot lacks review provenance')
    for row in legacy_data['samples']:
        if row['session_id'] in omitted_sessions:excluded.append(dict(origin='legacy:'+row['id'],reason='user_excluded_session'));continue
        path=legacy/row['image']
        if path.is_symlink() or not path.resolve().is_relative_to(legacy.resolve()):raise ValueError('Unsafe legacy image path')
        add(path,row['label'],'session:'+row['session_id'],'legacy:'+legacy.name+':'+row['id'],row['split'])
    return rows,excluded,legacy_data.get('fingerprint')

def build(lab_root,legacy,out):
    if out.exists():raise ValueError('Candidate snapshots are immutable; choose a new output directory')
    rows,excluded,legacy_fingerprint=load_rows(lab_root,legacy);input_count=len(rows);rows,quarantine=group_rows(rows);coverage,blockers=assign_splits(rows)
    out.mkdir(parents=True);(out/'images').mkdir();samples=[]
    for i,row in enumerate(rows):
        name=f'images/{i:06d}.png'
        with Image.open(row['source']) as source:source.convert('RGB').save(out/name)
        samples.append({k:v for k,v in dict(row,image=name).items() if k!='source'})
    fingerprint=hashlib.sha256(json.dumps(samples,sort_keys=True).encode()).hexdigest()
    result=dict(schema_version=1,kind='reviewed_native_crop_candidate',created_epoch=time.time(),fingerprint=fingerprint,legacy_fingerprint=legacy_fingerprint,classes=sorted({r['label'] for r in rows}),samples=samples,input_samples=input_count,unique_samples=len(samples),counts=dict(Counter(r['label'] for r in samples)),split_counts=dict(Counter(r['split'] for r in samples)),independent_groups=coverage,blockers=blockers,excluded=excluded,quarantine=quarantine,automatic_promotion=False,temporal_labels='Only explicit human track observations; no generated labels or interpolated ground truth')
    (out/'dataset.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);p.add_argument('--legacy',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();d=build(a.lab,a.legacy,a.out);print(json.dumps({k:d[k] for k in ['fingerprint','input_samples','unique_samples','counts','split_counts','independent_groups','blockers']},indent=2))
