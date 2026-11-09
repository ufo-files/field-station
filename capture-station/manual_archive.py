"""Priority publication of explicit manual captures, followed by reviewed updates."""
import hashlib,json,time
from pathlib import Path
from experiments import load

def enabled(archive,manifest):
 return bool(archive.config.get('manual_uploads_enabled') and manifest.get('capture_origin')=='manual' and manifest.get('started_epoch',0)>=archive.config.get('manual_uploads_since_epoch',0) and not manifest.get('validation') and not manifest.get('archive_withdrawn'))

def signature(path):
 s=path.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns]

def revision(folder,job=None):
 d=load(folder/'archive-decision.json',{})
 return d.get('review_revision') if d.get('bundle_ready') and d.get('export_version')==3 else (job or {}).get('manual_revision','baseline')

def plan(archive,job,manifest):
 from internet_archive import hashes
 from youtube_api import private_save
 from archive_tags import normalize
 from ce5_history import overlap
 folder=archive.folder(job['id']);rev=revision(folder,job)
 if job.get('manual_scope') and job.get('manual_revision')==rev and job.get('manual_plan_version')==2:return False
 previous=list(job.get('files',[]));verified=bool(job.get('verified_at'))
 tags=load(archive.data.parent/'archive-tags'/(job['id']+'.json'),{}).get('tags',[])
 approval=load(folder/'manual-archive-approval.json',{});decision=load(folder/'archive-decision.json',{})
 anomalous=approval.get('classification')=='anomalous' or decision.get('confirmed_anomalous') is True
 job.update(manual_scope=True,manual_revision=rev,manual_priority_epoch=max(manifest.get('stopped_epoch',0),decision.get('reviewed_epoch',0)),custom_tags=normalize([*tags,'manual-recording',*(['anomalous'] if anomalous else [])]),ce5_playback=overlap(archive.data.parent,manifest))
 names=['video.mp4','rf.jsonl','capture.log','capture-progress.txt','buffer-state.json','motion-events.json','rf-trigger-events.json','manual-archive-approval.json']
 if rev!='baseline':names+=['video-annotated.mp4','review-annotations.json','archive-decision.json','review-trim.json','video-trim.json','frames/reviewed-index.json']
 files=[];stats={}
 old={e['name']:e for e in previous};old_stats=job.get('source_signatures',{})
 receipt=load(folder/'manual-internet-archive.json',{})
 if receipt.get('state')=='verified' and receipt.get('identifier')==job['identifier']:
  for entry in receipt.get('files',[]):
   path=folder/entry['name']
   if entry.get('private_source') or not path.is_file() or path.is_symlink():continue
   stamp=signature(path)
   if stamp[2]==entry['bytes'] and stamp[3]/1e9<=receipt['verified_at']:
    old.setdefault(entry['name'],entry);old_stats.setdefault(entry['name'],stamp)

 for name in names:
  path=folder/name
  if not path.exists():
   if name=='video.mp4' or (rev!='baseline' and name in ('video-annotated.mp4','review-annotations.json','frames/reviewed-index.json')):raise ValueError('Manual recording evidence not ready: '+name)
   continue
  if path.is_symlink() or not path.is_file():raise ValueError('Unsafe manual recording evidence')
  stamp=signature(path)
  digest={k:old[name][k] for k in ('bytes','md5','sha256')} if name in old and old_stats.get(name)==stamp else hashes(path)
  if signature(path)!=stamp:raise ValueError('Manual recording changed during preparation')
  files.append(dict(name=name,**digest));stats[name]=stamp
 if rev!='baseline':
  index=load(folder/'frames/reviewed-index.json',{})
  if index.get('review_revision')!=rev:raise ValueError('Reviewed frames are still updating')
  for row in index.get('frames',[]):
   for kind in ('original','annotated'):
    entry=row[kind];path=folder/'frames'/entry['file']
    if path.is_symlink() or not path.resolve().is_relative_to((folder/'frames').resolve()):raise ValueError('Unsafe reviewed frame')
    digest=hashes(path)
    if digest['sha256']!=entry['sha256']:raise ValueError('Reviewed frame checksum changed')
    name=path.relative_to(folder).as_posix();files.append(dict(name=name,**digest));stats[name]=signature(path)
 if rev!='baseline':
  import re
  annotations=load(folder/'review-annotations.json',{}).get('annotations',[])
  for row in annotations:
   sample=row.get('annotation_id','')
   if not isinstance(sample,str) or not re.fullmatch('[a-f0-9]{32}',sample):continue
   review=archive.data.parent/'uap-lab/email-reviews/examples'/sample
   record=load(review/'review.json',{});crop=review/'native-object.png'
   if not record or record.get('deleted') or not crop.is_file():continue
   if crop.is_symlink():raise ValueError('Unsafe training crop')
   raw=crop.read_bytes()
   if hashlib.sha256(raw).hexdigest()!=record.get('native_crop_sha256'):raise ValueError('Reviewed crop checksum changed')
   private=archive.private/(job['id']+'-crop-'+sample+'.png');private.write_bytes(raw)
   name='crops/'+sample+'.png';files.append(dict(name=name,private_source=private.name,**hashes(private)));stats[name]=signature(private)
 timings=sorted((folder/'buffer-segments').glob('frame-times-*.jsonl'))
 if timings:
  import zipfile
  bundle=archive.private/(job['id']+'-frame-timing.zip')
  with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_DEFLATED) as output:
   for path in timings:
    if path.is_symlink():raise ValueError('Unsafe frame timing evidence')
    output.write(path,arcname=path.relative_to(folder).as_posix())
  files.append(dict(name='frame-timing.zip',private_source=bundle.name,**hashes(bundle)));stats['frame-timing.zip']=signature(bundle)
 metadata={k:v for k,v in manifest.items() if k not in ('internet_archive','youtube','upload')}
 metadata.update(publication_scope='manual_recording',review_revision=rev,classification=approval.get('classification'),annotations_included=rev!='baseline')
 snapshot=archive.private/(job['id']+'-manual-session.json');private_save(snapshot,metadata)
 files.append(dict(name='session.json',private_source=snapshot.name,**hashes(snapshot)))
 stats['session.json']=signature(snapshot)
 inventory=archive.private/(job['id']+'-manual-index.json')
 private_save(inventory,dict(schema=1,session_id=job['id'],review_revision=rev,files=files,excluded=['Duplicate MKV container; video.mp4 preserves original encoded video','Temporary capture segments','Unreviewed preview stills','Private configuration and credentials']))
 files.append(dict(name='archive-index.json',private_source=inventory.name,**hashes(inventory)));stats['archive-index.json']=signature(inventory)
 # Adopt a completed one-off upload without sending its unchanged video again.
 receipt=load(folder/'manual-internet-archive.json',{})
 reusable={e['name']:e['sha256'] for e in previous} if verified else {}
 if receipt.get('state')=='verified' and receipt.get('identifier')==job['identifier']:reusable.update({e['name']:e['sha256'] for e in receipt.get('files',[])})
 job.update(manual_plan_version=2,files=files,source_signatures=stats,total_bytes=sum(e['bytes'] for e in files),file_index=0,parts=[],uploaded_bytes=0,state='uploading',next_attempt=0,error=None,plan_version=5,review_revision=rev,reuse_verified_files={e['name']:e['sha256'] for e in files if reusable.get(e['name'])==e['sha256']})
 job.pop('upload_id',None);job.pop('verified_at',None)
 return True
