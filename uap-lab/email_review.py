"""Scrubbable alert evidence and explicit bounding-box review."""
import hashlib,io,json,math,os,re,shutil,subprocess,tempfile,time,uuid
from pathlib import Path
from review_playback import media_dir,native_path,playback_path,build_preview
from recognition_review import packets as encoded_frames
from PIL import Image
from email_training import store_review,LABELS,canonical_label

def folder_for(data,key):
 if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid alert')
 root=Path(data).parent/'notifications/outbox';folder=root/key
 if folder.is_symlink() or not (folder/'event.json').is_file():raise ValueError('Alert not found')
 return folder

def decoded_frames(path):
 import av
 result=[]
 with av.open(str(path)) as container:
  for frame in container.decode(video=0):
   result.append(dict(pts_time=float(frame.pts*frame.time_base),data_hash=hashlib.sha256(frame.to_ndarray(format='rgb24').tobytes()).hexdigest()))
 return result

def _prepare(data,key):
 folder=folder_for(data,key);target=folder/'review-clip.json'
 output_dir=media_dir(data,key);output_dir.mkdir(parents=True,exist_ok=True)
 if output_dir.is_symlink():raise ValueError('Unsafe review media directory')
 if target.exists() and native_path(data,key).is_file():
  result=json.loads(target.read_text())
  if not (output_dir/'playback.mp4').is_file():
   result.update(build_preview(native_path(data,key),output_dir/'playback.mp4'));temp=target.with_suffix('.tmp');temp.write_text(json.dumps(result));temp.replace(target)
  return result
 e=json.loads((folder/'event.json').read_text());spool=Path(data).parent/'capture-spool'/e['generation']
 preserved=folder/'review-source.json'
 if preserved.exists():
  from alert_evidence import backed_up
  if not backed_up(Path(data).parent,e,folder):raise ValueError('Preserved alert evidence is incomplete')
  entries=json.loads(preserved.read_text())['segments'];spool=Path(data).parent/'notifications/evidence'/e['generation']
 else:entries=[json.loads(line) for line in (spool/'segments-index.jsonl').read_text().splitlines()]
 selected=[v for v in entries if v['end']>=e['pts_seconds']-5 and v['start']<=e['pts_seconds']+5]
 if not selected:raise ValueError('No surrounding source segments available')
 if max(v['end'] for v in selected)<e['pts_seconds']+5 and not preserved.exists() and not (spool/'closed.json').exists():return dict(state='waiting_for_post_roll')
 ffmpeg=os.environ.get('FFMPEG','/opt/homebrew/bin/ffmpeg');ffprobe=os.environ.get('FFPROBE','/opt/homebrew/bin/ffprobe')
 with tempfile.TemporaryDirectory(dir=folder) as pins,tempfile.TemporaryDirectory(dir=output_dir) as temp:
  work=Path(temp);source_packets=[];lines=[]
  for i,entry in enumerate(selected):
   source=spool/entry['file']
   if source.parent!=spool or source.is_symlink() or not source.is_file():raise ValueError('Surrounding source segment unavailable')
   copied=Path(pins)/f'{i}.mkv';os.link(source,copied)
   with copied.open('rb') as handle:
    if hashlib.file_digest(handle,'sha256').hexdigest()!=entry['sha256']:raise ValueError('Source segment checksum mismatch')
   source_packets.extend(dict(source_pts=entry['start']+float(p['pts_time']),sha=p['data_hash']) for p in encoded_frames(copied));lines.append("file '"+str(copied).replace("'","'\\''")+"'")
  (work/'concat.txt').write_text('\n'.join(lines)+'\n')
  subprocess.run([ffmpeg,'-v','error','-f','concat','-safe','0','-i',str(work/'concat.txt'),'-map','0:v:0','-c','copy','-an','-movflags','+faststart',str(work/'clip.mp4')],check=True,capture_output=True,timeout=120)
  output=encoded_frames(work/'clip.mp4')
  if [p['data_hash'] for p in output]!=[p['sha'] for p in source_packets]:raise ValueError('Review clip changed or omitted native video frames')
  timeline=[dict(time=float(p['pts_time']),source_pts=s['source_pts']) for p,s in zip(output,source_packets)]
  if any(b['time']<=a['time'] for a,b in zip(timeline,timeline[1:])):raise ValueError('Nonmonotonic review video')
  event_frame=min(timeline,key=lambda p:abs(p['source_pts']-e['pts_seconds']))
  if abs(event_frame['source_pts']-e['pts_seconds'])>.003:raise ValueError('Review clip does not contain the alert frame')
  result=dict(state='ready',event_time=event_frame['time'],timeline=timeline,frames=len(timeline),source_frames_verified=True,verification='unchanged_encoded_slices_sha256',media_storage='runtime' if output_dir!=folder else 'event')
  result.update(build_preview(work/'clip.mp4',work/'playback.mp4'))
  (work/'clip.mp4').replace(output_dir/'review.mp4');(work/'playback.mp4').replace(output_dir/'playback.mp4');temp_json=folder/'review-clip.tmp';temp_json.write_text(json.dumps(result));temp_json.replace(target)
 return result

def event_reviews(data,key):
 """Use the atomic manifest as an index; read authoritative per-object records."""
 root=Path(data)/'email-reviews';examples=root/'examples';manifest=root/'training-manifest.json'
 try:
  from email_training import current_review_index
  index=current_review_index(data);batched=index is not None
  stamp=manifest.stat().st_mtime_ns if manifest.exists() else 0
  if not batched:index=json.loads(manifest.read_text())['examples']
  # A new example created after the index requires discovery, including recovery
  # from an interrupted write. Corrections/deletions are read from source below.
  if not batched and examples.stat().st_mtime_ns>stamp:raise ValueError('Index predates new examples')
  ids={r.get('sample_id',r.get('event_id')) for r in index if r.get('event_id')==key}
  if any(not isinstance(i,str) or not re.fullmatch('[a-f0-9]{32}',i) for i in ids):raise ValueError('Invalid index')
  paths=[examples/i/'review.json' for i in ids]
 except (OSError,ValueError,KeyError,TypeError):paths=list(examples.glob('*/review.json'))
 return [r for p in paths if (r:=json.loads(p.read_text())).get('event_id')==key]

def detail(data,key):
 folder=folder_for(data,key);e=json.loads((folder/'event.json').read_text());clip=json.loads((folder/'review-clip.json').read_text()) if (folder/'review-clip.json').exists() else (json.loads((folder/'review-error.json').read_text()) if (folder/'review-error.json').exists() else dict(state='preparing'))
 if clip.get('state')=='ready' and not native_path(data,key).is_file():
  retired=json.loads((folder/'local-media-retired.json').read_text()) if (folder/'local-media-retired.json').exists() else {}
  message='Video is retained in archive storage; its inspection copy needs restoration.' if retired.get('reason')=='internet_archive_verified' else 'Video was removed by retention; saved training frames remain.'
  clip=dict(clip,state='error',error=message) if (folder/'local-media-retired.json').exists() else dict(clip,state='preparing')
 if clip.get('state')=='ready' and native_path(data,key).is_file() and not (media_dir(data,key)/'playback.mp4').is_file():clip=dict(clip,state='preparing',phase='playback')
 annotations=[]
 for row in event_reviews(data,key):
  row['label']=canonical_label(row.get('label'))
  if row.get('event_id')==key and not row.get('deleted'):annotations.append(dict(row,sample_id=row.get('sample_id',row['event_id']),review_clip_time=row.get('review_clip_time',clip.get('event_time',0))))
 completion=folder/'review-completion.json';finished=json.loads(completion.read_text()) if completion.exists() else {}
 completed=finished.get('completed',False) and finished.get('annotation_revision')==annotation_revision(data,key)
 return dict(completed=completed,id=key,event=e,bounds=e['bounds'],label='anomalous',clip=dict({k:v for k,v in clip.items() if k!='timeline'},frame_times=[p['time'] for p in clip.get('timeline',[])]),annotations=sorted(annotations,key=lambda a:(a['review_clip_time'],a['reviewed_epoch'])),labels=sorted(LABELS|{'not_anomalous'}))

def save_review(data,body):
 import av
 key=body['id'];folder=folder_for(data,key);e=json.loads((folder/'event.json').read_text());clip=json.loads((folder/'review-clip.json').read_text());label=canonical_label(body['label'])
 if label not in LABELS|{'not_anomalous'}:raise ValueError('Choose a valid label')
 seconds=float(body['time']);timeline=clip['timeline']
 if not math.isfinite(seconds) or seconds<timeline[0]['time'] or seconds>timeline[-1]['time']+.1:raise ValueError('Choose a time within the video')
 selected=max((p for p in timeline if p['time']<=seconds+.001),key=lambda p:p['time'])
 image=None
 with av.open(str(native_path(data,key))) as c:
  c.seek(max(0,int(selected['time']*1000000)-1000000))
  for frame in c.decode(video=0):
   if abs(float(frame.pts*frame.time_base)-selected['time'])<.003:image=frame.to_image();break
 if image is None:raise ValueError('Selected native frame unavailable')
 bounds=body['bounds']
 if len(bounds)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds):raise ValueError('Draw a valid box')
 x,y,w,h=[round(v) for v in bounds]
 if w<3 or h<3 or x<0 or y<0 or x+w>image.width or y+h>image.height:raise ValueError('Box must fit within the native frame and be at least 3 pixels wide and high')
 output=io.BytesIO();image.crop((x,y,x+w,y+h)).save(output,format='PNG');crop=output.getvalue()
 sample_id=body.get('sample_id')
 if sample_id:
  if not re.fullmatch('[a-f0-9]{32}',sample_id):raise ValueError('Invalid annotation')
  existing=Path(data)/'email-reviews/examples'/sample_id/'review.json'
  if not existing.exists() or json.loads(existing.read_text()).get('event_id')!=key:raise ValueError('Annotation does not belong to this alert')
 else:sample_id=uuid.uuid4().hex
 record=dict(schema=1,event_id=key,sample_id=sample_id,message_id=uuid.uuid4().hex,reviewed_epoch=time.time(),label=label,human_confirmed=True,source='station_web_review',generation=e['generation'],sequence=None,pts_seconds=selected['source_pts'],review_clip_time=selected['time'],bounds=[x,y,w,h],model=e['model'],native_crop_sha256=hashlib.sha256(crop).hexdigest(),binary_anomalous=label=='anomalous',multiclass_ready=label!='not_anomalous',reviewer='station_web_ui',source_color_space='RGB')
 from review_archive import invalidate_event
 invalidate_event(data,key)
 state=store_review(data,record,crop)
 finish_review(data,dict(id=key,completed=True))
 return dict(state=state,review=record,completed=True)


def prepare(data,key):
 import fcntl
 folder=folder_for(data,key)
 with (folder/'review-build.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return dict(state='preparing')
  try:return _prepare(data,key)
  except Exception as exc:
   (folder/'review-error.json').write_text(json.dumps(dict(state='error',error=str(exc))))
   raise


def remove_review(data,body):
 key=body['id'];folder_for(data,key);sample_id=body['sample_id']
 if not re.fullmatch('[a-f0-9]{32}',sample_id):raise ValueError('Invalid annotation')
 folder=Path(data)/'email-reviews/examples'/sample_id;record=json.loads((folder/'review.json').read_text())
 if record['event_id']!=key:raise ValueError('Annotation does not belong to this alert')
 from review_archive import invalidate_event
 invalidate_event(data,key)
 record.update(deleted=True,source='station_web_review',message_id=uuid.uuid4().hex,reviewed_epoch=time.time(),sample_id=sample_id)
 state=store_review(data,record,(folder/'native-object.png').read_bytes())
 finish_review(data,dict(id=key,completed=True))
 return dict(state=state,completed=True)


def annotation_revision(data,key):
 rows=[]
 for r in event_reviews(data,key):
  if r.get('event_id')==key:rows.append((r.get('sample_id',r['event_id']),r['reviewed_epoch'],r.get('deleted',False)))
 return hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()

def finish_review(data,body):
 folder=folder_for(data,body['id'])
 if type(body.get('completed')) is not bool:raise ValueError('Choose a valid completion state')
 from review_archive import invalidate_event
 invalidate_event(data,body['id'])
 record=dict(completed=body['completed'],updated_epoch=time.time(),annotation_revision=annotation_revision(data,body['id']))
 target=folder/'review-completion.json';temp=folder/('review-completion-'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(record));temp.replace(target)
 return record
