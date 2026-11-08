"""Cached event-level metrics using capture timestamps, never review timestamps."""
import bisect,json,math,os,re,sqlite3,threading,time
from contextlib import closing
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
from astral import Observer
from astral.sun import sun
from retired_data import ids as retired_ids
TZ=ZoneInfo('America/Los_Angeles')
OBSERVER=Observer(37.7749,-122.4194)
_LOCK=threading.Lock();_CACHE={};_BUSY=set();_ERROR={}

def read(path,default):
 try:return json.loads(Path(path).read_text())
 except FileNotFoundError:return default

@lru_cache(maxsize=800)
def daylight(day):
 result=sun(OBSERVER,date=day,tzinfo=TZ)
 return result['sunrise'].timestamp(),result['sunset'].timestamp()

def merged(intervals):
 result=[]
 for start,end in sorted(intervals):
  if end<=start:continue
  if result and start<=result[-1][1]:result[-1][1]=max(end,result[-1][1])
  else:result.append([start,end])
 return result

def contains(intervals,stamp):
 i=bisect.bisect_right(intervals,[stamp,float('inf')])-1
 return i>=0 and intervals[i][0]<=stamp<intervals[i][1]

def audio_history(root):
 path=Path(root)/'audio/playback.sqlite3'
 if not path.exists():return [],[]
 with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
  playing=merged(db.execute('SELECT start,end FROM playback'))
  exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='coverage'").fetchone()
  coverage=merged(db.execute('SELECT start,end FROM coverage')) if exists else []
 return playing,coverage

def summarize(events,playing,coverage,now,days):
 hours=[dict(hour=h,total=0,daytime=0,nighttime=0,ce5_on=0,ce5_off=0,ce5_unknown=0) for h in range(24)]
 result=dict(total=0,daytime=0,nighttime=0,unknown_time=0,ce5_on=0,ce5_off=0,ce5_unknown=0,missing_time=0,hours=hours)
 cutoff=now-days*86400 if days else float('-inf')
 for stamp in events:
  if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp<=0:
   result['missing_time']+=1
   if not days:result['total']+=1;result['unknown_time']+=1;result['ce5_unknown']+=1
   continue
  if not cutoff<=stamp<=now:continue
  local=datetime.fromtimestamp(stamp,TZ);rise,setting=daylight(local.date())
  period='daytime' if rise<=stamp<setting else 'nighttime'
  audio='ce5_on' if contains(playing,stamp) else 'ce5_off' if contains(coverage,stamp) else 'ce5_unknown'
  for row in (result,hours[local.hour]):
   row['total']+=1;row[period]+=1;row[audio]+=1
 return result

def library_rows(data):
 import detection_library as library
 from recognition.recognition_alerts import recent_detections
 cached,_,error=library.refresh(data,wait=True)
 if cached is None or cached[0]==0:raise ValueError('Review library is still indexing')
 records=read(data/'email-reviews/training-manifest.json',{}).get('examples',[])
 samples,events=retired_ids(data,records);omitted=read(data/'omitted-objects.json',{}).get('objects',{})
 cutoff=read(data/'review-queue-cleared.json',{}).get('cutoff_epoch',float('-inf'))
 arrivals,_=recent_detections(data.parent/'notifications/outbox',cutoff)
 rows={row['id']:row for row in cached[1]};rows.update({row['id']:row for row in arrivals})
 from retired_data import visible
 return [row for row in library.current_reviews(list(rows.values()),records) if row['id'] not in omitted and visible(row,samples,events) and (row['human_reviewed'] or row.get('created',0)>cutoff)]

def station_video(meta):
 provenance=meta.get('provenance',{})
 return provenance.get('collection')!='PURSUE' and bool(re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',str(provenance.get('session_id',''))) or provenance.get('collection') in ('live-event','recorded-clip','model-detection','motion-collection'))

def build(data):
 data=Path(data);root=data.parent;rows=[row for row in library_rows(data) if row['label']=='anomalous']
 records=read(data/'email-reviews/training-manifest.json',{}).get('examples',[])
 reviews={(row.get('event_id'),row.get('sample_id') or row.get('event_id')):row for row in records}
 target=data/'observation-metrics';target.mkdir(parents=True,exist_ok=True)
 lanes={'human':[],'model':[]};legacy={}
 with closing(sqlite3.connect(target/'capture-times-v2.sqlite3',timeout=2)) as db:
  db.execute('CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, captured REAL, pts REAL)')
  known={key:(captured,pts) for key,captured,pts in db.execute('SELECT id,captured,pts FROM events')}
  pending=[]
  for row in rows:
   stamp=None
   if row['kind'] in ('review','detection'):
    key=row.get('video_id') or row['id']
    if key not in known:
     event=read(root/'notifications/outbox'/key/'event.json',{})
     captured=event.get('detected_epoch',row.get('detected_epoch'));pts=event.get('pts_seconds')
     if not isinstance(captured,(int,float)) or not math.isfinite(captured):captured=None
     if not isinstance(pts,(int,float)) or not math.isfinite(pts):pts=None
     known[key]=(captured,pts);pending.append((key,captured,pts))
    stamp,pts=known[key]
    review=reviews.get((key,row.get('sample_id') or key),{})
    if stamp is not None and pts is not None and isinstance(review.get('pts_seconds'),(int,float)):stamp+=review['pts_seconds']-pts
   elif row['kind'] in ('video','preserved'):
    # Imported training videos have upload dates, not established sighting dates.
    # Only explicit capture provenance may place them on time-of-day charts.
    source=data
    if row['kind']=='preserved':
     import labeled_frames
     source=labeled_frames.preserved_root()
    key=(row['kind'],row['video_id'])
    if key not in legacy:
     folder=source/'videos'/row['video_id'];meta=read(folder/'video.json',{});annotations=read(folder/'annotations.json',[])
     provenance=meta.get('provenance',{});station=station_video(meta)
     legacy[key]=(meta.get('captured_epoch',provenance.get('captured_epoch')),{a['id']:a.get('time',0) for a in annotations},station)
    captured,times,station=legacy[key]
    if not station:continue
    if isinstance(captured,(int,float)):stamp=captured+times.get(row.get('sample_id'),0)
   lanes['human' if row['human_reviewed'] else 'model'].append(stamp)
   if len(pending)>=100:
    with db:db.executemany('INSERT OR REPLACE INTO events VALUES (?,?,?)',pending)
    pending=[];time.sleep(.02)
  if pending:
   with db:db.executemany('INSERT OR REPLACE INTO events VALUES (?,?,?)',pending)
 playing,coverage=audio_history(root);now=time.time()
 return dict(schema=2,updated_epoch=now,timezone=str(TZ),location='San Francisco reference · SF Bay Area',scopes={name:{str(days):summarize(stamps,playing,coverage,now,days) for days in (1,7,30,0)} for name,stamps in lanes.items()})

def snapshot(data):
 data=Path(data);key=str(data);path=data/'observation-metrics/summary.json'
 with _LOCK:
  if key not in _CACHE:
   saved=read(path,{})
   if saved.get('schema')==2:_CACHE[key]=saved
  cached=_CACHE.get(key,{})
  if key not in _BUSY and time.time()-cached.get('updated_epoch',0)>60:
   _BUSY.add(key)
   def work():
    try:
     result=build(data);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result,allow_nan=False));temporary.replace(path)
     with _LOCK:_CACHE[key]=result;_ERROR.pop(key,None)
    except Exception:
     with _LOCK:_ERROR[key]='Metrics could not refresh. Retrying in the background.'
    finally:
     with _LOCK:_BUSY.discard(key)
   threading.Thread(target=work,daemon=True).start()
  return dict(cached,indexing=key in _BUSY,error=_ERROR.get(key),ready=bool(cached))
