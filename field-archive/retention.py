"""Automatic negative retention; model suggestions never become training labels."""
import argparse,collections,fcntl,hashlib,json,os,plistlib,re,sqlite3,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab'))
SAFE={'bird','insect','airplane','cloud','tree','other_animal','balloon','star','satellite','drone','not_anomalous'}
MEDIA={'.mkv','.mp4','.jpg','.jpeg','.png'}
def read(p,default=None):
 try:return json.loads(p.read_text())
 except FileNotFoundError:return default

def save(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.retention-tmp')
 with tmp.open('w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
 tmp.replace(p)

def human_negative(videos):
 if not videos:return False
 for folder,meta in videos:
  review=read(folder/'review.json',{});labels={a['label'] for a in read(folder/'annotations.json',[])}
  if not review.get('completed') or not labels<=SAFE or not(labels or review.get('no_target')):return False
 return True

def native_decision(root,session,db):
 m=read(session/'manifest.json',{});b=read(session/'buffer-state.json',{});gen=m.get('spool_generation');segments=b.get('segments',[])
 if not re.fullmatch(r'run-[a-f0-9]+',gen or '') or not segments:return dict(state='retain',reason='missing_native_provenance')
 ack=read(root/'capture-spool'/gen/'recognition-ack.json',{})
 if not ack.get('integrity_ok') or ack.get('generation')!=gen or ack.get('last_pts_seconds',-1)<segments[-1]['end']-.05:return dict(state='retain',reason='analysis_pending')
 from native_frames import timing_rows
 timing=timing_rows(session/'buffer-segments',segments[0]['start'],segments[-1]['end'])
 if not timing:timing=timing_rows(root/'capture-spool'/gen,segments[0]['start'],segments[-1]['end'])
 selected=[r for r in timing if segments[0]['start']<=r['pts_seconds']<segments[-1]['end']]
 if not selected or selected[0]['pts_seconds']>segments[0]['start']+.05 or selected[-1]['pts_seconds']<segments[-1]['end']-.05:return dict(state='retain',reason='incomplete_source_boundaries')
 expected=[r['sequence'] for r in selected]
 if not expected or expected!=list(range(expected[0],expected[-1]+1)):return dict(state='retain',reason='incomplete_source_timing')
 rows=db.execute('SELECT sequence,model,observations FROM frames WHERE generation=? AND sequence BETWEEN ? AND ? ORDER BY sequence',(gen,expected[0],expected[-1]))
 labels=collections.Counter();models=set();count=0
 for seq,model,encoded in rows:
  if count>=len(expected) or seq!=expected[count]:return dict(state='retain',reason='incomplete_analysis')
  count+=1;models.add(model)
  for o in json.loads(encoded):
   label=o.get('suggested_label');labels[label]+=1
   if o.get('classification_status')=='below_model_minimum_size':continue
   if label not in SAFE:return dict(state='retain',reason='anomalous_or_uncertain',label=label)
 if count!=len(expected) or len(models)!=1:return dict(state='retain',reason='incomplete_or_mixed_analysis')
 return dict(state='negative',reason='fully_analyzed_non_anomalous',generation=gen,first_sequence=expected[0],last_sequence=expected[-1],frames=count,labels=dict(labels),model=next(iter(models)),human_confirmed=False)

def inventory(folder,names=None):
 if folder.is_symlink():raise ValueError('Unsafe evidence directory')
 result=[]
 for p in (folder.rglob('*') if names is None else [folder/n for n in names]):
  if not p.exists():continue
  if p.is_symlink() or not p.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe media path')
  if p.is_file() and (names is not None or p.suffix.lower() in MEDIA):result.append((p,p.stat().st_size,p.stat().st_mtime_ns))
 return result

def cycle(root,audit,apply=False,provisional_cutoff=None):
 root=Path(root);data=root/'uap-lab';audit=Path(audit);audit.mkdir(parents=True,exist_ok=True)
 report=dict(epoch=time.time(),apply=apply,eligible=0,eligible_bytes=0,deleted_files=0,unlinked_bytes=0,skipped={},errors=[]);skipped=collections.Counter();linked=collections.defaultdict(list)
 for p in (data/'videos').glob('*/video.json'):
  meta=read(p);linked[meta.get('provenance',{}).get('session_id')].append((p.parent,meta))
 reviews=[read(p) for p in (data/'email-reviews/examples').glob('*/review.json')]
 active={r.get('video_id') for p in (data/'runs').glob('*/run.json') if (r:=read(p)).get('state') not in ('complete','completed','failed','cancelled')}
 database=data/'recognition/results.sqlite'
 if not database.exists():
  report.update(phase='waiting_for_first_analysis',finished_epoch=time.time());save(audit/'status.json',report);return report
 db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=10)
 try:
  for session in sorted((root/'sessions').iterdir()):
   try:
    if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',session.name):continue
    manifest=read(session/'manifest.json',{});videos=linked[session.name]
    if manifest.get('capture_origin')!='provisional_motion' or manifest.get('state')!='completed':skipped['manual_or_incomplete']+=1;continue
    if manifest.get('session_media_removed'):
     receipt=read(audit/'receipts'/(session.name+'.json'),{})
     if apply and receipt and not receipt.get('completed'):
      for entry in receipt['files']:
       p=root/entry['path']
       if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe resumed cleanup path')
       if p.exists():
        if p.stat().st_size!=entry['bytes'] or p.stat().st_mtime_ns!=entry['mtime_ns']:raise ValueError('Media changed after interrupted cleanup')
        p.unlink();report['deleted_files']+=1;report['unlinked_bytes']+=entry['bytes']
      receipt['completed']=True;save(audit/'receipts'/(session.name+'.json'),receipt)
     continue
    decision_file=read(session/'archive-decision.json',{})
    if decision_file.get('human_confirmed') and decision_file.get('confirmed_anomalous'):skipped['confirmed_anomaly']+=1;continue
    if any(f.name in active for f,m in videos):skipped['active_analysis']+=1;continue
    if read(session/'buffer-state.json',{}).get('state')!='assembled':skipped['assembly_pending']+=1;continue
    if time.time()-max((session/'manifest.json').stat().st_mtime,manifest.get('stopped_epoch',0))<120:skipped['recent']+=1;continue
    if provisional_cutoff is not None:
     if manifest.get('stopped_epoch',float('inf'))>provisional_cutoff:skipped['after_hourly_cutoff']+=1;continue
     if any(read(f/'annotations.json',[]) or read(f/'review.json',{}).get('completed') for f,m in videos):skipped['protected_training_video']+=1;continue
     segments=read(session/'buffer-state.json',{}).get('segments',[])
     if segments and any(not r.get('deleted') and r.get('generation')==manifest.get('spool_generation') and segments[0]['start']<=r.get('pts_seconds',-1)<=segments[-1]['end'] for r in reviews):skipped['protected_email_review_video']+=1;continue
     decision=dict(state='negative',reason='user_authorized_provisional_hourly_cleanup',hourly_cutoff=provisional_cutoff)
    else:
     decision=dict(state='negative',reason='human_reviewed_non_anomalous') if human_negative(videos) else native_decision(root,session,db)
    # Human positive/uncertain annotations always override model-only disposal.
    if any(any(a.get('label') not in SAFE for a in read(f/'annotations.json',[])) for f,m in videos):decision=dict(state='retain',reason='protected_human_labels')
    segments=read(session/'buffer-state.json',{}).get('segments',[])
    if segments and any(not r.get('deleted') and r.get('label') not in SAFE and r.get('generation')==manifest.get('spool_generation') and segments[0]['start']<=r.get('pts_seconds',-1)<=segments[-1]['end'] for r in reviews):decision=dict(state='retain',reason='protected_email_or_web_label')
    if decision['state']!='negative':skipped[decision['reason']]+=1;continue
    guards=[session/'manifest.json']+[f/n for f,m in videos for n in ('review.json','annotations.json','video.json')]
    snapshots={p:p.read_bytes() if p.exists() else None for p in guards}
    files=inventory(session)
    for f,m in videos:
     # Keep all reviewed training sources, crops, annotations and temporal labels.
     if read(f/'annotations.json',[]) or read(f/'review.json',{}).get('completed'):continue
     files+=inventory(f,['source','preview.mp4'])
    report['eligible']+=1;report['eligible_bytes']+=sum(size for p,size,stamp in files)
    if not apply:continue
    if any((p.read_bytes() if p.exists() else None)!=v for p,v in snapshots.items()):raise ValueError('Review changed during cleanup')
    for p,size,stamp in files:
     if p.is_symlink() or (p.stat().st_size,p.stat().st_mtime_ns)!=(size,stamp):raise ValueError('Media changed during cleanup')
    receipt=dict(session=session.name,decision=decision,epoch=time.time(),files=[dict(path=str(p.relative_to(root)),bytes=size,mtime_ns=stamp) for p,size,stamp in files])
    save(audit/'receipts'/(session.name+'.json'),receipt)
    # Tombstones precede unlink so intake and UI cannot requeue expired media.
    manifest.update(session_media_removed=True,cleanup_reason=decision['reason']);save(session/'manifest.json',manifest)
    q=data/'provisional-queue'/(session.name+'.json');job=read(q,{})
    job.update(session_id=session.name,state='discarded',classification=decision['reason'],automatic_deletion=True,retention=decision);save(q,job)
    for f,m in videos:
     if not read(f/'annotations.json',[]) and not read(f/'review.json',{}).get('completed'):
      m.update(media_expired=True,retention=decision);save(f/'video.json',m)
    for p,size,stamp in files:p.unlink();report['deleted_files']+=1;report['unlinked_bytes']+=size
    receipt['completed']=True;save(audit/'receipts'/(session.name+'.json'),receipt);save(session/'cleanup-receipt.json',receipt)
   except Exception as exc:report['errors'].append(dict(session=session.name,error=str(exc)))
 finally:db.close()
 report['skipped']=dict(skipped);report['finished_epoch']=time.time();save(audit/'status.json',report);return report

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args();cfg=read(Path(args.config));root=Path(cfg['root']);audit=Path(cfg['audit']);audit.mkdir(parents=True,exist_ok=True)
 with (audit/'worker.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  info=plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist',str(root)]))
  if not os.path.ismount(root) or info.get('VolumeUUID')!=cfg['volume_uuid']:raise ValueError('Station volume identity mismatch')
  if args.apply:
   from alert_evidence import preserve
   save(audit/'alert-evidence.json',preserve(root))
  print(json.dumps(cycle(root,audit,args.apply)),flush=True)
if __name__=='__main__':main()
