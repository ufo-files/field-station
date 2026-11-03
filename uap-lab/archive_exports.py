"""One raw/annotated archive bundle per session, authorized only by completed web reviews."""
import bisect,hashlib,json,os,re,subprocess,tempfile,time
from pathlib import Path
from collections import defaultdict
SID=re.compile(r'[0-9TZ]+-[a-f0-9]{6}')

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def matching_sessions(ranges,event,clip):
 pts=event.get('pts_seconds',-1);generation=event.get('generation')
 matches=[r for r in ranges if r[1]==generation and r[2]<=pts<r[3]]
 timeline=clip.get('timeline',[])
 if clip.get('source_frames_verified') and timeline:
  start=min(p['source_pts'] for p in timeline);end=max(p['source_pts'] for p in timeline)
  matches=[r for r in matches if r[2]<=start+.001 and r[3]>=end-.001]
  # Overlapping recordings can legitimately contain the exact same native frames.
  # Choose one deterministically; align_annotations still verifies packet identity.
  matches=sorted(matches,key=lambda r:(r[3]-r[2],r[2],r[0]))[:1]
 return [r[0] for r in matches]

def reviewed_clip(data,key,folder,rows):
 import lab
 from email_review import prepare
 clip=lab.read(folder/'review-clip.json',{})
 if not clip.get('source_frames_verified') or not (folder/'review.mp4').is_file():clip=prepare(data,key)
 if clip.get('state')!='ready' or not clip.get('source_frames_verified'):raise ValueError('Verified detection clip is not ready')
 annotations=[]
 for original in rows:
  row=dict(original)
  if 'review_clip_time' not in row:
   pts=row.get('pts_seconds')
   if pts is None:raise ValueError('Reviewed detection has no source timestamp')
   timeline=clip.get('timeline',[])
   if not timeline:raise ValueError('Reviewed detection has no verified timeline')
   frame=min(timeline,key=lambda p:abs(p['source_pts']-pts))
   if abs(frame['source_pts']-pts)>.003:raise ValueError('Reviewed detection is absent from the source clip')
   row['review_clip_time']=frame['time']
  annotations.append(row)
 return clip,annotations

def collect(data,sessions):
 import lab
 groups=defaultdict(list);blocked=[];ranges=[]
 for p in sessions.glob('*/manifest.json'):
  m=lab.read(p,{});segments=lab.read(p.parent/'buffer-state.json',{}).get('segments',[])
  if segments:ranges.append((p.parent.name,m.get('spool_generation'),segments[0]['start'],segments[-1]['end']))
 for p in (data/'videos').glob('*/video.json'):
  m=lab.read(p,{});review=lab.read(p.parent/'review.json',{});sid=m.get('provenance',{}).get('session_id')
  if not SID.fullmatch(sid or '') or not review.get('completed') or review.get('automated_event'):continue
  annotations=lab.read(p.parent/'annotations.json',[])
  groups[sid].append(dict(kind='video',id=m['id'],source=str(p.parent/'source'),sha256=m['sha256'],reviewed_epoch=review.get('reviewed_at',0),annotations=annotations))
 examples=defaultdict(list);revisions=defaultdict(list)
 for p in (data/'email-reviews/examples').glob('*/review.json'):
  row=lab.read(p,{})
  if row.get('event_id'):revisions[row['event_id']].append((row.get('sample_id',row['event_id']),row['reviewed_epoch'],row.get('deleted',False)))
  if row.get('source')=='station_web_review' and row.get('human_confirmed') and not row.get('deleted'):examples[row['event_id']].append(row)
 for key,rows in examples.items():
  folder=data.parent/'notifications/outbox'/key;finished=lab.read(folder/'review-completion.json',{})
  if not finished.get('completed') or finished.get('annotation_revision')!=hashlib.sha256(json.dumps(sorted(revisions[key])).encode()).hexdigest():continue
  try:clip,rows=reviewed_clip(data,key,folder,rows)
  except Exception as exc:
   blocked.append(dict(event_id=key,state='blocked',reason=str(exc)));continue
  event=lab.read(folder/'event.json',{});matches=matching_sessions(ranges,event,clip)
  if len(matches)!=1:
   if any(r.get('label')=='anomalous' for r in rows):blocked.append(dict(event_id=key,state='blocked',reason='Original session mapping is missing or ambiguous'))
   continue
  groups[matches[0]].append(dict(kind='alert_web',id=key,source=str(folder/'review.mp4'),reviewed_epoch=finished['updated_epoch'],annotations=rows))
 return dict(groups),blocked

def command(args):
 import lab
 result=subprocess.run(args,env=lab.ENV,capture_output=True,timeout=1800)
 if result.returncode:raise ValueError(result.stderr.decode(errors='replace')[-1500:])
 return result

def ensure_source(folder,groups):
 import lab
 raw=folder/'video.mkv';playback=folder/'video.mp4'
 if not raw.exists():
  source=next((Path(g['source']) for g in groups if g['kind']=='video' and Path(g['source']).is_file()),None)
  if source:
   from evidence_copy import copy_evidence
   copy_evidence(source,raw)
  else:
   m=lab.read(folder/'manifest.json',{});segments=lab.read(folder/'buffer-state.json',{}).get('segments',[])
   if not segments:raise ValueError('Complete original session video is unavailable')
   root=folder.parent.parent;paths=[]
   for entry in segments:
    name=entry['file']
    if not re.fullmatch(r'segment-\d+\.mkv',name):raise ValueError('Invalid source segment')
    choices=[folder/'buffer-segments'/name,root/'capture-spool'/m['spool_generation']/name,root/'notifications/evidence'/m['spool_generation']/name]
    source=next((p for p in choices if p.is_file() and not p.is_symlink()),None)
    if source is None:raise ValueError('Complete session cannot be restored; missing '+name+' (review clips retained)')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Source checksum mismatch')
    paths.append(source)
   with tempfile.TemporaryDirectory(dir=folder) as temp:
    work=Path(temp);listing=work/'source.txt';listing.write_text('\n'.join("file '"+str(p)+"'" for p in paths))
    command([lab.FFMPEG,'-v','error','-f','concat','-safe','0','-i',str(listing),'-map','0','-c','copy',str(work/'raw.mkv')]);(work/'raw.mkv').replace(raw)
   state=lab.read(folder/'buffer-state.json',{});state.update(state='assembled',restored_by_archive=True);lab.save(folder/'buffer-state.json',state)
 if raw.is_symlink():raise ValueError('Unsafe raw video')
 if not playback.exists():
  temp=folder/'archive-raw-tmp.mp4';command([lab.FFMPEG,'-v','error','-i',str(raw),'-map','0','-c','copy','-movflags','+faststart','-y',str(temp)]);temp.replace(playback)
 from recognition_review import packets
 before=sorted(packets(raw),key=lambda r:r['pts_time']);after=sorted(packets(playback),key=lambda r:r['pts_time'])
 if [r['data_hash'] for r in before]!=[r['data_hash'] for r in after]:raise ValueError('Raw playback does not preserve the original video frames')
 return raw,playback

def align_annotations(raw,groups):
 import lab
 from recognition_review import packets
 native=sorted(packets(raw),key=lambda r:r['pts_time']);hashes=[p['data_hash'] for p in native];annotations=[]
 probe=json.loads(command([lab.FFPROBE,'-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(raw)]).stdout)['streams'][0];width,height=probe['width'],probe['height']
 for group in groups:
  path=Path(group['source'])
  if not path.is_file():raise ValueError('Reviewed original source is unavailable')
  movie=sorted(packets(path),key=lambda r:r['pts_time']);target=[p['data_hash'] for p in movie]
  matches=[i for i,h in enumerate(hashes) if target and h==target[0] and hashes[i:i+len(target)]==target]
  if len(matches)!=1:raise ValueError('Reviewed clip does not uniquely match original session frames')
  offset=matches[0];times=[p['pts_time']-(movie[0]['pts_time'] if group['kind']=='video' else 0) for p in movie]
  for a in group['annotations']:
   t=float(a['time'] if group['kind']=='video' else a['review_clip_time'])
   if group['kind']=='video':index=a.get('frame_index') if a.get('frame_index') is not None else bisect.bisect_left(times,t-1e-6)
   else:index=min(range(len(times)),key=lambda i:abs(times[i]-t))
   if index>=len(times) or (group['kind']!='video' and abs(times[index]-t)>.003):raise ValueError('Reviewed frame timestamp does not match source')
   if group['kind']=='video':b=a['bounds'];box=[round(b['x']*width),round(b['y']*height),round(b['w']*width),round(b['h']*height)]
   else:box=list(a['bounds'])
   x,y,w,h=box
   if min(w,h)<3 or min(x,y)<0 or x+w>width+1 or y+h>height+1:raise ValueError('Reviewed box is outside original video')
   label=a['label']
   if not re.fullmatch(r'[a-z_]+',label):raise ValueError('Invalid label')
   annotations.append(dict(frame=offset+index,bounds=box,label=label,review_id=group['id'],annotation_id=a.get('id',a.get('sample_id'))))
 return annotations,len(native),width,height

def render(folder,raw,annotations,frames,width,height):
 import lab
 filters=[]
 for a in annotations:
  x,y,w,h=a['bounds'];color='yellow' if a['label']=='anomalous' else 'cyan';enable="eq(n,"+str(a['frame'])+")"
  filters.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=4:enable='{enable}'")
 with tempfile.TemporaryDirectory(dir=folder) as temp:
  work=Path(temp);script=work/'boxes.txt';script.write_text(','.join(filters) or 'null');out=work/'video-annotated.mp4'
  command([lab.FFMPEG,'-v','error','-threads','2','-i',str(raw),'-map','0:v:0','-map','0:a?','-vf',script.read_text(),'-fps_mode','passthrough','-enc_time_base:v','1:1000000','-video_track_timescale','1000000','-c:v','libx264','-threads','2','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(out)])
  info=json.loads(command([lab.FFPROBE,'-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=nb_read_frames,width,height','-of','json',str(out)]).stdout)['streams'][0]
  if (int(info['nb_read_frames']),info['width'],info['height'])!=(frames,width,height):raise ValueError('Annotated export changed frame count or dimensions')
  verify_timing(raw,out)
  out.replace(folder/'video-annotated.mp4')

def render_stills(folder,raw,annotations,width,height,revision):
 """Lossless full-size decoded sources paired with every explicitly reviewed frame."""
 import av
 from PIL import ImageDraw
 import lab
 grouped=defaultdict(list)
 for row in annotations:grouped[row['frame']].append(row)
 if not grouped:raise ValueError('No reviewed frames to export')
 if min(grouped)<0:raise ValueError('Invalid reviewed frame index')
 parent=folder/'frames'
 if parent.is_symlink():raise ValueError('Unsafe frames directory')
 parent.mkdir(exist_ok=True)
 name='reviewed-'+revision
 destination=parent/name
 if destination.is_symlink():raise ValueError('Unsafe reviewed frames directory')
 entries=[]
 with tempfile.TemporaryDirectory(dir=parent) as temp:
  work=Path(temp)
  with av.open(str(raw)) as container:
   for number,frame in enumerate(container.decode(video=0)):
    if number>max(grouped):break
    if number not in grouped:continue
    original=frame.to_image()
    if original.size!=(width,height):raise ValueError('Reviewed still dimensions differ from original video')
    annotated=original.copy();draw=ImageDraw.Draw(annotated)
    for row in grouped[number]:
     x,y,w,h=row['bounds'];color='yellow' if row['label']=='anomalous' else 'cyan'
     draw.rectangle((x,y,x+w-1,y+h-1),outline=color,width=4)
     draw.text((x,max(0,y-12)),row['label'],fill=color,stroke_width=1,stroke_fill='black')
    entry=dict(frame=number,source_pts_seconds=float(frame.pts*frame.time_base),width=width,height=height,annotations=grouped[number])
    for kind,image in [('original',original),('annotated',annotated)]:
     filename=f'frame-{number:09d}-{kind}.png';image.save(work/filename)
     entry[kind]=dict(file=name+'/'+filename,sha256=hashlib.sha256((work/filename).read_bytes()).hexdigest())
    entries.append(entry)
  if len(entries)!=len(grouped):raise ValueError('Not every reviewed frame exists in original video')
  # Revision-specific files are committed before the index makes them publishable.
  destination.mkdir(exist_ok=True)
  for path in work.iterdir():path.replace(destination/path.name)
 index=dict(schema=1,mode='reviewed',review_revision=revision,source_video='video.mp4',
  original_encoding='Lossless PNG of full-resolution decoded source video; no crop or resize.',
  annotation_count=len(annotations),frames=entries)
 lab.save(parent/'reviewed-index.json',index)
 return index

def stills_ready(folder,revision):
 import lab
 index=lab.read(folder/'frames/reviewed-index.json',{})
 if index.get('review_revision')!=revision or not index.get('frames'):return False
 for row in index['frames']:
  for kind in ('original','annotated'):
   item=row.get(kind,{});name=item.get('file','')
   if not re.fullmatch(r'reviewed-[a-f0-9]{64}/frame-[0-9]{9}-(original|annotated)\.png',name):return False
   path=folder/'frames'/name
   if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):return False
 return True

def verify_timing(raw,out):
 import lab
 def timeline(path):
  rows=json.loads(command([lab.FFPROBE,'-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)]).stdout)['frames']
  return [float(r['best_effort_timestamp_time']) for r in rows]
 before,after=timeline(raw),timeline(out)
 if len(before)!=len(after) or any(abs((a-after[0])-(b-before[0]))>.002 for a,b in zip(after,before)):raise ValueError('Annotated export changed frame timing')

def reconcile():
 import lab
 data=lab.DATA;sessions=Path(os.environ.get('CAPTURE_DATA',str(lab.STATION/'sessions')));groups,errors=collect(data,sessions);states=[]
 for old in sessions.glob('*/archive-decision.json'):
  d=lab.read(old,{})
  if d.get('source')=='station_web_ui' and old.parent.name not in groups and d.get('bundle_ready'):
   d.update(bundle_ready=False,human_confirmed=False);lab.save(old,d)
 for sid,reviews in sorted(groups.items()):
  folder=sessions/sid;m=lab.read(folder/'manifest.json',{})
  if m.get('archive_withdrawn'):states.append(dict(session_id=sid,state='withdrawn'));continue
  anomalous=any(a['label']=='anomalous' for r in reviews for a in r['annotations']);revision=digest(reviews)
  decision=dict(schema=2,source='station_web_ui',export_version=3,session_id=sid,human_confirmed=True,confirmed_anomalous=anomalous,reviewed_epoch=max(r['reviewed_epoch'] for r in reviews),review_revision=revision,bundle_ready=False)
  previous=lab.read(folder/'archive-decision.json',{})
  if previous.get('export_version')==3 and stills_ready(folder,revision) and previous.get('review_revision')==revision and previous.get('bundle_ready') and all((folder/n).is_file() for n in ('video.mp4','video-annotated.mp4')):states.append(dict(session_id=sid,state='ready',revision=revision));continue
  lab.save(folder/'archive-decision.json',decision)
  if not anomalous:states.append(dict(session_id=sid,state='not_anomalous'));continue
  try:
   raw,playback=ensure_source(folder,reviews);annotations,count,width,height=align_annotations(raw,reviews)
   lab.save(folder/'review-annotations.json',dict(schema=1,session_id=sid,review_revision=revision,annotations=annotations,boxes_only_on_explicitly_reviewed_frames=True))
   if previous.get('review_revision')!=revision or not previous.get('bundle_ready') or not (folder/'video-annotated.mp4').is_file():render(folder,raw,annotations,count,width,height)
   stills=render_stills(folder,raw,annotations,width,height,revision)
   # Publish eligibility only after both complete videos and annotations exist.
   latest,_=collect(data,sessions)
   if digest(latest.get(sid,[]))!=revision:raise ValueError('Review changed during export; awaiting updated export')
   decision.update(bundle_ready=True,videos=['video.mp4','video-annotated.mp4'],annotation_count=len(annotations),frame_count=count,reviewed_frame_count=len(stills['frames']),stills_index='frames/reviewed-index.json')
   lab.save(folder/'archive-decision.json',decision);(data/'archive-decisions').mkdir(exist_ok=True);lab.save(data/'archive-decisions'/(sid+'.json'),decision)
   m=lab.read(folder/'manifest.json',m)
   m.update(session_media_removed=False,video_playback=dict(state='completed',frame_count=count));lab.save(folder/'manifest.json',m)
   states.append(dict(session_id=sid,state='ready',revision=revision,annotations=len(annotations)))
  except Exception as exc:states.append(dict(session_id=sid,state='blocked',error=str(exc)))
 lab.save(data/'archive-review-status.json',dict(updated_epoch=time.time(),sessions=states,errors=errors))
 return states


def watch():
 import lab,fcntl
 lock=lab.DATA/'archive-export.lock'
 with lock.open('a') as stream:
  try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  while True:
   try:reconcile()
   except Exception as exc:print('Archive export:',str(exc),flush=True)
   time.sleep(30)
