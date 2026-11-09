"""Manual session inventory; recording labels never create frame training labels."""
import base64,json,re
from pathlib import Path
from urllib.parse import urlencode

SID=re.compile(r'[0-9TZ]+-[a-f0-9]{6}')
def read(path,default):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return default

def listing(data,station,before='',limit=100):
 data,station=Path(data),Path(station)
 limit=max(1,min(100,int(limit)))
 # The durable manual-session index is independent of the detection backlog.
 records=read(data/'live/manual-sessions.json',[])
 sessions=station/'sessions';rows=[];seen=set()
 for record in reversed(records):
  sid=record.get('session_id','')
  if not SID.fullmatch(sid) or sid in seen:continue
  seen.add(sid);folder=sessions/sid
  if folder.is_symlink():continue
  m=read(folder/'manifest.json',{})
  if not m:continue
  if m.get('capture_origin')!='manual' and 'manual' not in m.get('title','').lower():continue
  approval=read(folder/'manual-archive-approval.json',{})
  reviewed=approval.get('human_confirmed') is True and approval.get('session_id')==sid
  label=approval.get('classification') if reviewed else None
  if label not in ('anomalous','not_anomalous'):label=None;reviewed=False
  receipt=read(folder/'manual-internet-archive.json',{})
  normal=m.get('internet_archive',{})
  if normal.get('verified_at') and normal.get('state') in ('retaining','cleaned'):receipt=dict(normal,state='verified')
  job=read(sessions.resolve().parent/'manual-archive-uploads'/sid/'job.json',{})
  if normal.get('state'):job=normal
  playback=m.get('video_playback',{}).get('state')
  ready=m.get('state')!='recording' and playback=='completed' and (folder/'video.mp4').is_file()
  state='recording' if m.get('state')=='recording' else 'ready' if ready else 'failed' if playback=='failed' or m.get('state')=='failed' else 'preparing'
  url='/api/live/artifact?'+urlencode(dict(session=sid,name='video.mp4')) if ready else None
  archive=receipt.get('url') if receipt.get('state')=='verified' else None
  if archive and not re.fullmatch(r'https://archive.org/details/[A-Za-z0-9_.-]+',archive):archive=None
  rows.append(dict(id='manual:'+sid,session_id=sid,kind='manual_recording',created=m.get('started_epoch',record.get('created',0)),
   review_url='/manual-review?'+urlencode(dict(session=sid)) if ready else None,state=state,duration_seconds=m.get('elapsed_seconds'),label=label,human_reviewed=reviewed,video_url=url,archive_url=archive,
   upload_state=job.get('state') or ('verified' if archive else 'preparing' if approval.get('upload_requested') else 'queued')))
 rows.sort(key=lambda r:(r['created'],r['id']),reverse=True);total=len(rows)
 if before:
  try:stamp,key=json.loads(base64.urlsafe_b64decode(before));rows=[r for r in rows if (r['created'],r['id'])<(stamp,key)]
  except Exception:raise ValueError('Invalid recording cursor')
 page=rows[:limit];cursor=None
 if len(rows)>limit:cursor=base64.urlsafe_b64encode(json.dumps([page[-1]['created'],page[-1]['id']]).encode()).decode()
 return dict(items=page,total=total,counts={'manual_recordings':total},filter_counts=None,counts_indexing=False,indexing=False,ready=True,index_error=None,next_cursor=cursor,labels=[])


def register_review(data,station,sid):
 """Create an annotation workspace, not a machine detection or training label."""
 import hashlib,time
 if not SID.fullmatch(sid):raise ValueError('Invalid manual recording')
 data,station=Path(data),Path(station);session=station/'sessions'/sid
 if session.is_symlink():raise ValueError('Unsafe session')
 m=read(session/'manifest.json',{})
 if m.get('capture_origin')!='manual':raise ValueError('Not a manual recording')
 if m.get('state') not in ('completed','interrupted') or m.get('video_playback',{}).get('state')!='completed':raise ValueError('Manual video is still preparing')
 source=session/'video.mp4'
 if not source.is_file() or source.is_symlink():raise ValueError('Manual recording unavailable')
 buffer=read(session/'buffer-state.json',{});segments=buffer.get('segments',[])
 if not segments:raise ValueError('Manual recording timing unavailable')
 key=hashlib.sha256(('manual-recording:'+sid).encode()).hexdigest()[:32]
 folder=data.parent/'notifications/outbox'/key
 if folder.is_symlink():raise ValueError('Unsafe review workspace')
 folder.mkdir(parents=True,exist_ok=True)
 from recognition.recognition_alerts import atomic
 if not (folder/'event.json').exists():
  atomic(folder/'delivery.json',dict(state='suppressed',reason='Manual recording annotation workspace; not a detection'))
  event=dict(schema=3,id=key,kind='manual_recording',manual_session_id=sid,created_epoch=m['started_epoch'],
   detected_epoch=None,generation=m.get('spool_generation') or 'manual:'+sid,pts_seconds=segments[0]['start']+buffer.get('trim_start_seconds',0),sequence=None,
   classification=None,model=None,bounds=None,score=None,screenshots=[])
  atomic(folder/'event.json',event)
 return key


def prepare_review(data,key,folder,output_dir):
 import os
 from review_playback import frame_times,build_preview
 from recognition.recognition_alerts import atomic
 event=read(folder/'event.json',{});sid=event.get('manual_session_id','')
 if not SID.fullmatch(sid):raise ValueError('Invalid manual recording')
 session=Path(data).parent/'sessions'/sid;source=session/'video.mp4'
 if session.is_symlink() or source.is_symlink() or not source.is_file():raise ValueError('Manual recording unavailable')
 # Read the protected original directly, including when review storage is on another drive.
 native=source
 target=folder/'review-clip.json';result=read(target,{})
 if result.get('state')=='ready' and (output_dir/'playback.mp4').is_file():return result
 times=frame_times(native)
 if not times or any(b<=a for a,b in zip(times,times[1:])):raise ValueError('Invalid native recording timeline')
 result=dict(state='ready',event_time=times[0],timeline=[dict(time=t,source_pts=event['pts_seconds']+t-times[0]) for t in times],
  frames=len(times),source_frames_verified=True,verification='manual_original',media_storage='manual_session')
 result.update(build_preview(native,output_dir/'playback.mp4',timeout=900,original_times=times))
 atomic(target,result)
 return result
