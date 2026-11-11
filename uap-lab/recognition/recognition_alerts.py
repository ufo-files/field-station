"""Notify on the first anomalous frame; group repeats across unstable proposal IDs."""
import hashlib,json,math,os,time,sqlite3
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont


def atomic(path,value):
 temp=path.with_suffix('.tmp')
 with temp.open('w') as f:json.dump(value,f,allow_nan=False);f.flush();os.fsync(f.fileno())
 temp.replace(path)

def notice_path(root):
 runtime=os.environ.get('XDG_RUNTIME_DIR')
 return (Path(runtime) if runtime else Path(root))/'latest-detection.json'

def feed_path(root):return notice_path(root).with_name('detection-arrivals.sqlite')

def feed_connect(root):
 p=feed_path(root);p.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(p,timeout=2);db.execute('PRAGMA journal_mode=WAL')
 db.execute('CREATE TABLE IF NOT EXISTS arrivals(id TEXT PRIMARY KEY,created REAL NOT NULL,payload TEXT NOT NULL)')
 db.execute('CREATE INDEX IF NOT EXISTS arrivals_created ON arrivals(created)')
 db.execute('CREATE TABLE IF NOT EXISTS coverage(id INTEGER PRIMARY KEY,after REAL NOT NULL)')
 return db

def feed_row(event):
 key=event['id'];label=event.get('classification')
 if label not in ('anomalous','not_anomalous'):return None
 return dict(id=key,kind='detection',created=event['created_epoch'],detected_epoch=event.get('detected_epoch'),label=label,human_reviewed=False,model_label=label,image_url='/api/label-queue/image?id='+key,frame_url='/api/label-queue/image?full=1&id='+key,review_url='/email-review?id='+key)

def record_arrivals(root,events,complete_since=None):
 db=feed_connect(root)
 try:
  with db:
   for event in events:
    row=feed_row(event)
    if row:db.execute('INSERT OR IGNORE INTO arrivals VALUES (?,?,?)',(row['id'],row['created'],json.dumps(row)))
   if complete_since is not None:db.execute('INSERT OR REPLACE INTO coverage VALUES (1,?)',(complete_since,))
 finally:db.close()

def recent_detections(root,after):
 p=feed_path(root)
 if not p.exists():return [],False
 db=None
 try:
  db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=.2)
  rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM arrivals WHERE created>? ORDER BY created DESC',(after,))]
  coverage=db.execute('SELECT after FROM coverage WHERE id=1').fetchone()
  return rows,bool(coverage and after>=coverage[0])
 except (OSError,sqlite3.Error,ValueError):return [],False
 finally:
  if db is not None:db.close()

def publish_notice(root,event):
 try:
  # Publish the review row before the navigation hint, so the dot has a target.
  record_arrivals(root,[event])
  if event.get('classification')!='anomalous':return
  p=notice_path(root);p.parent.mkdir(parents=True,exist_ok=True)
  atomic(p,dict(id=event['id'],epoch=event['created_epoch']))
 except (OSError,sqlite3.Error):pass # Navigation hints must never interrupt detection capture.

def render_screenshot(frame,bounds,path):
 """Preserve the full frame; separately save clean native and enlarged object crops."""
 image=Image.fromarray(frame).convert('RGB');w,h=image.size;x,y,bw,bh=map(int,bounds)
 if bw<=0 or bh<=0 or x<0 or y<0 or x+bw>w or y+bh>h:raise ValueError('Invalid native object bounds')
 image.save(path.with_name('source-frame.png'))
 # The visible review rectangle is the exact source region used for BOTH the detail and training crop.
 from crop_geometry import context_bounds
 bx,by,mark_w,mark_h=context_bounds(bounds,w,h)
 crop=image.crop((bx,by,bx+mark_w,by+mark_h));crop.save(path.with_name('native-object.png'))
 scale=max(1,1024/max(crop.size));detail=crop.resize((round(crop.width*scale),round(crop.height*scale)),Image.Resampling.BICUBIC)
 detail.save(path.with_name('object-detail.png'))
 draw=ImageDraw.Draw(image);rect=(bx,by,bx+mark_w-1,by+mark_h-1)
 draw.rectangle(rect,outline='#101820',width=7)
 draw.rectangle((bx+2,by+2,bx+mark_w-3,by+mark_h-3),outline='#ffdc00',width=3)
 temporary=path.with_suffix('.tmp');image.save(temporary,format='PNG');temporary.replace(path)
 return [bx,by,mark_w,mark_h]

class AlertOutbox:
 def __init__(self,root,not_before=0):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.not_before=not_before;self.groups=[]
  p=self.root/'producer-state.json';self.state=json.loads(p.read_text()) if p.exists() else {};self.groups=self.state.get('groups',[]);self.watermark=self.state.get('watermark',{});self.saved_at=0
  # Recover publication that completed immediately before a state-checkpoint crash.
  for g in self.groups:
   key=g.get('id')
   if g.get('notified') or not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):continue
   p=self.root/key/'event.json'
   try:e=json.loads(p.read_text())
   except FileNotFoundError:continue
   if not e.get('test') and 'group_first_pts' in e and e.get('group_id')==key:g['notified']=True
 def persist(self,force=False):
  if force or time.monotonic()-self.saved_at>=1:
   atomic(self.root/'producer-state.json',dict(schema=2,groups=self.groups,watermark=self.watermark));self.saved_at=time.monotonic()
 def submit(self,generation,row,indices,crops):
  if len(indices)!=len(crops):raise ValueError('Alert crops do not match classified observations')
  if row['received_epoch']<self.not_before:return 0
  if self.watermark.get('generation')==generation and row['sequence']<=self.watermark.get('sequence',-1):return 0
  self.watermark=dict(generation=generation,sequence=row['sequence'])
  pts=row['pts_seconds'];self.groups=[g for g in self.groups if g['generation']==generation and 0<=pts-g['last']<=(10 if g.get('notified') else 1)]
  used=set();queued=0;changed=False
  for i in indices:
   obs=row['observations'][i]
   if obs.get('suggested_label') not in ('anomalous','not_anomalous'):continue
   x,y,w,h=obs['box'];cx=x+w/2;cy=y+h/2
   choices=[(math.hypot(cx-g['cx'],cy-g['cy']),j,g) for j,g in enumerate(self.groups) if j not in used and g.get('classification','anomalous')==obs['suggested_label']]
   choice=min(choices,key=lambda t:t[0]) if choices else None
   if choice and choice[0]<=max(64,2*max(w,h)):
    _,j,g=choice;used.add(j)
    if row['sequence']>g['sequence']:g['hits']+=1
    g.update(cx=cx,cy=cy,last=pts,sequence=row['sequence'])
   else:
    g=dict(classification=obs['suggested_label'],id=hashlib.sha256(f'{generation}:{row["sequence"]}:{i}:{x}:{y}'.encode()).hexdigest()[:32],generation=generation,first=pts,last=pts,cx=cx,cy=cy,hits=1,sequence=row['sequence']);self.groups.append(g);used.add(len(self.groups)-1);changed=True
   if g.get('notified'):continue
   frame=row.get('alert_frame')
   if frame is None:continue
   key=g['id'];folder=self.root/key;folder.mkdir(exist_ok=True)
   if folder.is_symlink():raise ValueError('Unsafe alert directory')
   if (folder/'event.json').exists():g['notified']=True;changed=True;continue
   review_bounds=render_screenshot(frame,obs['box'],folder/'object.png')
   event=dict(schema=3,id=key,created_epoch=time.time(),detected_epoch=row['received_epoch'],generation=generation,sequence=row['sequence'],pts_seconds=pts,track=obs['proposed_track_id'],model=obs['model'],score=obs['scores']['anomalous'],bounds=review_bounds,detection_bounds=obs['box'],flag_source='model',human_confirmed=False,screenshots=['object.png','object-detail.png'],native_crop='native-object.png',native_crop_sha256=hashlib.sha256((folder/'native-object.png').read_bytes()).hexdigest(),screenshot_description='Uncropped original frame with a yellow box, plus the exact boxed region smoothly enlarged with bicubic interpolation to at least 1024 pixels on its longest side. Display smoothing does not add captured detail',classification=obs['suggested_label'],review_only=obs['suggested_label']!='anomalous',scientific_qualification=False,persistence_seconds=pts-g['first'],grouped_observations=g['hits'],group_first_pts=g['first'],group_id=g['id'])
   if obs.get('night_context'):event['night_context']=obs['night_context']
   if row.get('alert_color_source'):
    event['review_color_source']=row['alert_color_source'];event['source_color_space']='RGB'
   # Suppress mail before publication, including older notification workers.
   if event['review_only']:atomic(folder/'delivery.json',dict(state='suppressed',reason='Review-only non-anomalous detection'))
   # Publish once per spatial episode; unrelated objects never wait for a quota.
   if not (folder/'event.json').exists():
    atomic(folder/'event.json',event);publish_notice(self.root,event)
    from review_color import request
    request(folder)
   g['notified']=True;queued+=1
  self.persist(force=bool(queued) or changed);return queued
