"""Private, checksum-verified capacity offload. No age-based candidate deletion."""
import argparse,hashlib,json,os,plistlib,shutil,sqlite3,subprocess,sys,tarfile,time
from pathlib import Path

def read(p,default=None):
    return json.loads(p.read_text()) if p.exists() else default
def save(p,value):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp')
    with tmp.open('w') as f:json.dump(value,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    tmp.replace(p)
    fd=os.open(p.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def checked(root,name):
    root=Path(root);relative=Path(name);p=root/relative
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:raise ValueError('Unsafe archive path')
    top=root/relative.parts[0]
    if top.is_symlink():
        # Only explicitly registered external roots may cross a filesystem boundary.
        spec=read(root/'retention-policy.json',{}).get('storage_aliases',{}).get(top.name,{})
        if not spec:raise ValueError('Unregistered storage alias')
        volume=Path(spec['volume']);target=Path(spec['target'])
        if not volume.is_mount() or (volume/'.field-spool-volume').read_text().strip()!=spec['identity'] or top.resolve()!=target.resolve() or not target.resolve().is_relative_to(volume.resolve()):raise ValueError('Storage alias unavailable')
        if p==top:return p
        if p.is_symlink() or any(x.is_symlink() for x in p.parents if x!=top and x.is_relative_to(top)) or not p.resolve().is_relative_to(target.resolve()):raise ValueError('Unsafe archive path')
    elif p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or any(x.is_symlink() for x in p.parents if x!=root and x.is_relative_to(root)):
        raise ValueError('Unsafe archive path')
    return p
def pressure(total,free,active,policy):
    used=1-free/total
    return used>policy['target_used_fraction'] if active else used>=policy['offload_used_fraction']
NEGATIVE_LABELS={'not_anomalous','bird','insect','airplane','cloud','other_animal','balloon','star','satellite','shooting_star','vehicle','drone'}
def negative_annotations(annotations):
    return bool(annotations) and all(a.get('label') in NEGATIVE_LABELS for a in annotations)
def video_rows(root):
    # Avoid negative exists/stat probes for optional metadata on a full SSD.
    from concurrent.futures import ThreadPoolExecutor
    folder=root/'uap-lab/videos'
    if not folder.exists():return []
    def one(p):
        try:names=set(os.listdir(p))
        except (FileNotFoundError,NotADirectoryError):return None
        if 'video.json' not in names:return None
        values={}
        for name,default in [('video.json',{}),('annotations.json',[]),('review.json',{})]:
            try:values[name]=json.loads((p/name).read_text()) if name in names else default
            except FileNotFoundError:values[name]=default
        return p,values
    with ThreadPoolExecutor(max_workers=4) as pool:return [v for v in pool.map(one,folder.iterdir()) if v is not None]
def protection_snapshot(root):
    sessions=set();reviews={};active=set();leases=read(root/'uap-lab/review-leases.json',{});now=time.time()
    for p in (root/'uap-lab/runs').glob('*/run.json'):
        r=read(p,{})
        if r.get('state') not in ('complete','completed','failed','cancelled'):active.add(r.get('video_id'))
    for folder,values in video_rows(root):
        meta=values['video.json'];annotations=values['annotations.json'];review=values['review.json']
        negative=negative_annotations(annotations) or (not annotations and review.get('completed') and review.get('no_target'))
        if leases.get(folder.name,0)>now or folder.name in active or ((annotations or review.get('completed')) and not negative):
            sessions.add(meta.get('provenance',{}).get('session_id'))
    manifest=root/'uap-lab/email-reviews/training-manifest.json'
    if manifest.exists():
        index=read(manifest)
        if not isinstance(index,dict) or not isinstance(index.get('examples'),list):raise ValueError('Review protection index invalid')
        rows=index['examples']
    else:rows=(read(p,{}) for p in (root/'uap-lab/email-reviews/examples').glob('*/review.json'))
    for r in rows:
        if r.get('deleted') or r.get('retired'):continue
        if r.get('human_confirmed') and not r.get('deleted') and r.get('label') in NEGATIVE_LABELS:continue
        reviews.setdefault(r.get('generation'),[]).append(r.get('pts_seconds',-100))
    return sessions,reviews
def protected(root,sid,context=None):
    session=root/'sessions'/sid;m=read(session/'manifest.json',{})
    if m.get('capture_origin')!='provisional_motion' or m.get('state')!='completed':return True
    decision=read(session/'archive-decision.json',{})
    if decision.get('human_confirmed') and decision.get('confirmed_anomalous') is not False:return True
    sessions,reviews=context if context is not None else protection_snapshot(root)
    if sid in sessions:return True
    segments=read(session/'buffer-state.json',{}).get('segments',[])
    if segments and any(segments[0]['start']-5<=pts<=segments[-1]['end']+5 for pts in reviews.get(m.get('spool_generation'),[])):return True
    return False
def eligible(root,sid,context=None):
    if sid.startswith('recognition-'):return shard_eligible(root,sid)
    session=checked(root,'sessions/'+sid);m=read(session/'manifest.json',{})
    if m.get('session_media_removed') or protected(root,sid,context):return False
    b=read(session/'buffer-state.json',{});segments=b.get('segments',[])
    if b.get('state')!='assembled' or not segments or time.time()-max(m.get('stopped_epoch',time.time()),(session/'manifest.json').stat().st_mtime)<120:return False
    gen=m.get('spool_generation','');spool=checked(root,'capture-spool/'+gen)
    for name in ('analysis-ack.json','recognition-ack.json'):
        ack=read(spool/name,{})
        if not ack.get('integrity_ok') or ack.get('generation')!=gen or ack.get('last_pts_seconds',-1)<segments[-1]['end']-.001:return False
    return True
def shard_path(root,sid):
    return checked(root,'uap-lab/recognition/partitions/'+sid.removeprefix('recognition-')+'.sqlite')
def shard_eligible(root,sid):
    p=shard_path(root,sid)
    if not p.is_file() or time.time()-p.stat().st_mtime<120:return False
    db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
    try:ranges=list(db.execute('SELECT generation,min(pts),max(pts) FROM frames GROUP BY generation'))
    finally:db.close()
    for gen,start,end in ranges:
        ack=read(checked(root,'capture-spool/'+gen+'/recognition-ack.json'),{})
        if not ack.get('integrity_ok') or ack.get('generation')!=gen or ack.get('last_pts_seconds',-1)<end:return False
        for mpath in (root/'sessions').glob('*/manifest.json'):
            m=read(mpath,{})
            if m.get('session_media_removed') or m.get('spool_generation')!=gen:continue
            segments=read(mpath.parent/'buffer-state.json',{}).get('segments',[])
            if not segments or (segments[0]['start']<=end and segments[-1]['end']>=start):return False
        for rpath in (root/'uap-lab/email-reviews/examples').glob('*/review.json'):
            r=read(rpath,{})
            if r.get('deleted') or r.get('retired'):continue
            if r.get('generation')==gen and start-5<=r.get('pts_seconds',-100)<=end+5:return False
    return bool(ranges)
def inventory(root,sid):
    if not eligible(root,sid):raise ValueError('Session protected or analysis incomplete')
    if sid.startswith('recognition-'):
        p=shard_path(root,sid);st=p.stat()
        return dict(schema=1,session=sid,files=[dict(path=str(p.relative_to(root)),bytes=st.st_size,mtime_ns=st.st_mtime_ns,sha256=digest(p))])
    folders=[root/'sessions'/sid]
    for p in (root/'uap-lab/videos').glob('*/video.json'):
        if read(p,{}).get('provenance',{}).get('session_id')==sid:folders.append(p.parent)
    files=[]
    for folder in folders:
        for p in sorted(folder.rglob('*')):
            checked(root,str(p.relative_to(root)))
            if p.is_file():
                st=p.stat();files.append(dict(path=str(p.relative_to(root)),bytes=st.st_size,mtime_ns=st.st_mtime_ns,sha256=digest(p)))
    return dict(schema=1,session=sid,files=files)
def verify_unchanged(root,unit,media_only=False):
    if not eligible(root,unit['session']):raise ValueError('Session became protected')
    for e in unit['files']:
        p=checked(root,e['path'])
        if media_only and p.suffix.lower() not in ('.mkv','.mp4','.wav','.flac') and p.name!='source':continue
        st=p.stat()
        if st.st_size!=e['bytes'] or st.st_mtime_ns!=e['mtime_ns'] or digest(p)!=e['sha256']:raise ValueError('Source changed after backup: '+e['path'])
def evict(root,unit,receipt):
    if receipt!=fingerprint(unit):raise ValueError('Archive receipt mismatch')
    verify_unchanged(root,unit,media_only=True)
    sid=unit['session'];record=dict(verified_archive=receipt,epoch=time.time(),reason='capacity_offload')
    save(root/'retention/receipts'/(sid+'.json'),dict(unit=unit,receipt=record))
    if sid.startswith('recognition-'):
        shard_path(root,sid).unlink()
        save(root/'retention/receipts'/(sid+'.json'),dict(unit=unit,receipt=record,completed=True,unlinked_files=1))
        return dict(unlinked_files=1)
    m=read(root/'sessions'/sid/'manifest.json',{});m.update(session_media_removed=True,retention=record);save(root/'sessions'/sid/'manifest.json',m)
    queue=root/'uap-lab/provisional-queue'/(sid+'.json');job=read(queue,{})
    job.update(session_id=sid,state='archived',retention=record);save(queue,job)
    for p in (root/'uap-lab/videos').glob('*/video.json'):
        meta=read(p,{})
        if meta.get('provenance',{}).get('session_id')==sid:meta.update(media_expired=True,retention=record);save(p,meta)
    # Keep metadata and labels locally; full originals live in the verified archive.
    count=0
    for e in unit['files']:
        p=checked(root,e['path'])
        # Native labeled crops and review images remain local for training and browsing.
        if p.suffix.lower() in ('.mkv','.mp4','.wav','.flac') or p.name=='source':
            p.unlink();count+=1
    save(root/'retention/receipts'/(sid+'.json'),dict(unit=unit,receipt=record,completed=True,unlinked_files=count))
    return dict(unlinked_files=count)
def main():
    a=argparse.ArgumentParser();a.add_argument('action',choices=['status','inventory','export','evict']);a.add_argument('--root',default='/Volumes/UFO-Field');a.add_argument('--session');a.add_argument('--receipt');args=a.parse_args();root=Path(args.root)
    cfg=read(root/'retention-policy.json',{})
    info=plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist',str(root)]))
    if not root.is_mount() or info.get('VolumeUUID')!=cfg.get('volume_uuid'):raise ValueError('Wrong field SSD')
    if (root/'.field-station-volume').read_text().strip()!=cfg['volume_marker']:raise ValueError('Wrong field marker')
    if args.action=='status':
        usage=shutil.disk_usage(root);old=read(root/'retention/status.json',{});active=pressure(usage.total,usage.free,old.get('offloading',False),cfg)
        result=dict(epoch=time.time(),offloading=active,free_bytes=usage.free,total_bytes=usage.total,reserve_bytes=cfg['reserve_gib']*1024**3,candidates=[])
        if active:
            context=protection_snapshot(root)
            for p in sorted((root/'sessions').glob('*/manifest.json')):
                if eligible(root,p.parent.name,context):result['candidates'].append(p.parent.name)
                if len(result['candidates'])>=10:break
            if cfg.get('offload_recognition_partitions',False) and len(result['candidates'])<10:
                for p in sorted((root/'uap-lab/recognition/partitions').glob('*.sqlite')):
                    sid='recognition-'+p.stem
                    if eligible(root,sid):result['candidates'].append(sid)
                    if len(result['candidates'])>=10:break
        save(root/'retention/status.json',result);print(json.dumps(result));return
    if not args.session or '/' in args.session or args.session in ('.','..'):raise ValueError('Invalid session')
    manifest=root/'retention/units'/(args.session+'.json')
    if args.action=='inventory':
        unit=inventory(root,args.session);save(manifest,unit);print(json.dumps(unit));return
    unit=read(manifest)
    if args.action=='export':
        verify_unchanged(root,unit)
        with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as t:
            for e in unit['files']:t.add(checked(root,e['path']),arcname=e['path'],recursive=False)
    elif args.action=='evict':print(json.dumps(evict(root,unit,args.receipt)))
if __name__=='__main__':main()
