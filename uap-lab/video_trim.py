"""Reversible session trims; native source and training annotations stay unchanged."""
import bisect,hashlib,json,math,os,re,statistics,time,uuid
from pathlib import Path
from label_queue import read

def session_for(data,key):
 from email_review import folder_for
 folder_for(data,key)
 groups=read(Path(data)/'archive-review-groups.json',{}).get('groups',{})
 matches=[sid for sid,items in groups.items() if any(g.get('kind')=='alert_web' and g.get('id')==key for g in items)]
 if not matches:
  from session_catalog import lookup
  from archive_exports import matching_sessions
  out=Path(data).parent/'notifications/outbox'/key;event=read(out/'event.json',{});clip=read(out/'review-clip.json',{})
  candidates=lookup(Path(data).parent,event.get('generation'),event.get('pts_seconds',-1)) or [];ranges=[]
  for candidate in candidates:
   segments=read(candidate/'buffer-state.json',{}).get('segments',[])
   if segments:ranges.append((candidate.name,event.get('generation'),segments[0]['start'],segments[-1]['end']))
  matches=matching_sessions(ranges,event,clip)
 if len(matches)!=1:raise ValueError('This detection is not yet linked to one recording. Try again after export indexing finishes.')
 sid=matches[0]
 if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Invalid recording')
 folder=Path(data).parent/'sessions'/sid
 if folder.is_symlink():raise ValueError('Unsafe recording path')
 return folder

def status(data,key):
 try:folder=session_for(data,key)
 except ValueError:return dict(available=False)
 request=read(folder/'review-trim.json',{})
 decision=read(folder/'archive-decision.json',{})
 export=read(Path(data)/'archive-review-status.json',{});error=next((r.get('error') for r in export.get('sessions',[]) if r.get('session_id')==folder.name),None) if export.get('updated_epoch',0)>=request.get('saved_epoch',float('inf')) else None
 applied=bool(request and decision.get('trim_revision')==request.get('revision') and decision.get('bundle_ready'))
 # Superseded exports retry automatically; an old pass must not report failure
 # after the requested revision has already finished.
 retrying=error=='Review changed during export; awaiting updated export'
 from archive_links import bundle_url
 return dict(available=True,session_id=folder.name,bundle_url=bundle_url(folder),request=request,error=None if applied or retrying else error,applied=applied)

def save(data,body):
 from email_review import folder_for
 import lab
 key=body.get('id','');out=folder_for(data,key);folder=session_for(data,key)
 if body.get('reset') is True:request=dict(enabled=False,event_id=key)
 else:
  clip=read(out/'review-clip.json',{});timeline=clip.get('timeline',[])
  if not clip.get('source_frames_verified') or len(timeline)<2:raise ValueError('Wait for the original video to finish preparing.')
  try:start=float(body['start']);end=float(body['end'])
  except (KeyError,TypeError,ValueError):raise ValueError('Enter valid start and end times.') from None
  times=[p['time'] for p in timeline];duration=times[-1]+statistics.median(b-a for a,b in zip(times,times[1:]))
  if not all(math.isfinite(t) for t in (start,end)) or start<times[0]-.003 or end>duration+.01 or end<=start:raise ValueError('Choose a start before the end, within this video.')
  first=max(0,bisect.bisect_right(times,start+.001)-1);last=bisect.bisect_left(times,end-.001)
  if last<=first:raise ValueError('The trim must contain at least one frame.')
  request=dict(enabled=True,event_id=key,start=times[first],end=times[last] if last<len(times) else duration,start_frame=first,end_frame=last,timeline_hash=hashlib.sha256(json.dumps(timeline,sort_keys=True).encode()).hexdigest())
 request.update(revision=uuid.uuid4().hex,saved_epoch=time.time())
 with (Path(data)/'email-reviews/review.lock').open('a') as lock:
  import fcntl
  fcntl.flock(lock,fcntl.LOCK_EX)
  old=read(folder/'review-trim.json',{})
  history=folder/'trim-history';history.mkdir(exist_ok=True)
  if old:lab.save(history/(old['revision']+'.json'),old)
  lab.save(folder/'review-trim.json',request)
  decision=read(folder/'archive-decision.json',{});decision['bundle_ready']=False;lab.save(folder/'archive-decision.json',decision)
 return dict(saved=True,**status(data,key))

def apply(folder,raw,annotations):
 """Build the primary MP4 from unchanged native encoded frames, then rebase boxes."""
 import lab
 from recognition_review import packets
 from archive_exports import packet_offset,command
 request=read(folder/'review-trim.json',{})
 native=sorted(packets(raw),key=lambda p:p['pts_time']);start=0;end=len(native)
 if request.get('enabled'):
  from review_playback import native_path
  key=request['event_id'];data=folder.parent.parent/'uap-lab'
  clip=read(folder.parent.parent/'notifications/outbox'/key/'review-clip.json',{})
  if hashlib.sha256(json.dumps(clip.get('timeline',[]),sort_keys=True).encode()).hexdigest()!=request['timeline_hash']:raise ValueError('The source clip changed; choose the trim again.')
  movie=sorted(packets(native_path(data,key)),key=lambda p:p['pts_time'])
  offset=packet_offset([p['data_hash'] for p in native],[p['data_hash'] for p in movie])
  start=offset+request['start_frame'];end=offset+request['end_frame']
  if not 0<=start<end<=len(native):raise ValueError('The selected trim extends outside the original recording.')
  if any(a['label']=='anomalous' for a in annotations) and not any(a['label']=='anomalous' and start<=a['frame']<end for a in annotations):raise ValueError('The Archive trim must include a reviewed anomalous frame.')
 target=folder/'video.mp4';temp=folder/('trim-'+uuid.uuid4().hex+'.mp4')
 try:
  args=[lab.FFMPEG,'-v','error','-i',str(raw)]
  if start or end<len(native):
   times=[p['pts_time'] for p in native];step=statistics.median(b-a for a,b in zip(times,times[1:]));finish=times[end] if end<len(times) else times[-1]+step
   args+=['-ss',str(times[start]),'-t',str(finish-times[start])]
  command(args+['-map','0:v:0','-an','-c:v','copy','-avoid_negative_ts','make_zero','-movflags','+faststart',str(temp)])
  result=sorted(packets(temp),key=lambda p:p['pts_time'])
  if [p['data_hash'] for p in result]!=[p['data_hash'] for p in native[start:end]]:raise ValueError('The recording cannot be trimmed at these exact frames without changing its encoded source.')
  temp.replace(target)
 finally:temp.unlink(missing_ok=True)
 info=dict(schema=1,trim_revision=request.get('revision'),enabled=bool(request.get('enabled')),original_video='video.mkv',video='video.mp4',source_start_frame=start,source_end_frame=end,frame_count=end-start,original_frame_count=len(native),encoding='unchanged_native_encoded_frames',annotations_outside_trim_preserved_in_stills=True)
 lab.save(folder/'video-trim.json',info)
 return target,[dict(a,frame=a['frame']-start) for a in annotations if start<=a['frame']<end],end-start


def download(data,key):
 info=status(data,key)
 if not info.get('applied'):raise ValueError('The saved trim is still preparing.')
 folder=session_for(data,key);path=folder/'video.mp4'
 if path.is_file() and not path.is_symlink():return path
 receipt=read(folder/'manifest.json',{}).get('internet_archive',{});identifier=receipt.get('identifier','')
 if receipt.get('verified_at') and receipt.get('state') in ('retaining','cleaned') and re.fullmatch('[A-Za-z0-9_.-]+',identifier):return 'https://archive.org/download/'+identifier+'/video.mp4'
 raise ValueError('The trimmed video is unavailable; the full original remains preserved.')
