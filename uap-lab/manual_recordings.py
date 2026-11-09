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
  job=read(sessions.parent/'manual-archive-uploads'/sid/'job.json',{})
  playback=m.get('video_playback',{}).get('state')
  ready=m.get('state')!='recording' and playback=='completed' and (folder/'video.mp4').is_file()
  state='recording' if m.get('state')=='recording' else 'ready' if ready else 'failed' if playback=='failed' or m.get('state')=='failed' else 'preparing'
  url='/api/live/artifact?'+urlencode(dict(session=sid,name='video.mp4')) if ready else None
  archive=receipt.get('url') if receipt.get('state')=='verified' else None
  if archive and not re.fullmatch(r'https://archive.org/details/[A-Za-z0-9_.-]+',archive):archive=None
  rows.append(dict(id='manual:'+sid,session_id=sid,kind='manual_recording',created=m.get('started_epoch',record.get('created',0)),
   state=state,duration_seconds=m.get('elapsed_seconds'),label=label,human_reviewed=reviewed,video_url=url,archive_url=archive,
   upload_state='verified' if archive else job.get('state','preparing' if approval.get('upload_requested') else None)))
 rows.sort(key=lambda r:(r['created'],r['id']),reverse=True);total=len(rows)
 if before:
  try:stamp,key=json.loads(base64.urlsafe_b64decode(before));rows=[r for r in rows if (r['created'],r['id'])<(stamp,key)]
  except Exception:raise ValueError('Invalid recording cursor')
 page=rows[:limit];cursor=None
 if len(rows)>limit:cursor=base64.urlsafe_b64encode(json.dumps([page[-1]['created'],page[-1]['id']]).encode()).decode()
 return dict(items=page,total=total,counts={'manual_recordings':total},filter_counts=None,counts_indexing=False,indexing=False,ready=True,index_error=None,next_cursor=cursor,labels=[])
