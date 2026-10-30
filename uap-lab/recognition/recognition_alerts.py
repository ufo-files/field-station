"""Group sustained spatial detections independently of unstable proposal IDs."""
import hashlib,json,math,os,time
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

COOLDOWN=1800

def atomic(path,value):
 temp=path.with_suffix('.tmp')
 with temp.open('w') as f:json.dump(value,f,allow_nan=False);f.flush();os.fsync(f.fileno())
 temp.replace(path)

def render_screenshot(frame,bounds,path):
 """Preserve the full frame; separately save clean native and enlarged object crops."""
 image=Image.fromarray(frame).convert('RGB');w,h=image.size;x,y,bw,bh=map(int,bounds)
 if bw<=0 or bh<=0 or x<0 or y<0 or x+bw>w or y+bh>h:raise ValueError('Invalid native object bounds')
 image.save(path.with_name('source-frame.png'))
 # The visible review rectangle is the exact source region used for BOTH the detail and training crop.
 mark_w=min(w,max(64,bw+24));mark_h=min(h,max(64,bh+24))
 bx=max(0,min(w-mark_w,round(x+bw/2-mark_w/2)));by=max(0,min(h-mark_h,round(y+bh/2-mark_h/2)))
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
  p=self.root/'producer-state.json';self.state=json.loads(p.read_text()) if p.exists() else {};self.last=self.state.get('last_queued_epoch',0)
  # Fail closed across restarts even if an old installation lacked producer state.
  for p in self.root.glob('*/event.json'):
   event=json.loads(p.read_text())
   if not event.get('test'):self.last=max(self.last,event.get('created_epoch',0))
 def wants_frame(self):return time.time()-self.last>=COOLDOWN
 def submit(self,generation,row,indices,crops):
  if len(indices)!=len(crops):raise ValueError('Alert crops do not match classified observations')
  if row['received_epoch']<self.not_before or not self.wants_frame():return 0
  pts=row['pts_seconds'];self.groups=[g for g in self.groups if g['generation']==generation and 0<=pts-g['last']<=1]
  used=set()
  for i in indices:
   obs=row['observations'][i]
   if obs.get('suggested_label')!='anomalous':continue
   x,y,w,h=obs['box'];cx=x+w/2;cy=y+h/2
   choices=[(math.hypot(cx-g['cx'],cy-g['cy']),j,g) for j,g in enumerate(self.groups) if j not in used]
   choice=min(choices,key=lambda t:t[0]) if choices else None
   if choice and choice[0]<=max(64,2*max(w,h)):
    _,j,g=choice;used.add(j)
    if row['sequence']>g['sequence']:g['hits']+=1
    g.update(cx=cx,cy=cy,last=pts,sequence=row['sequence'])
   else:
    if len(self.groups)>=128:continue
    g=dict(generation=generation,first=pts,last=pts,cx=cx,cy=cy,hits=1,sequence=row['sequence']);self.groups.append(g);used.add(len(self.groups)-1)
   if pts-g['first']<2 or g['hits']<10:continue
   frame=row.get('alert_frame')
   if frame is None:continue
   key=hashlib.sha256(f'{generation}:{g["first"]}:{row["sequence"]}'.encode()).hexdigest()[:32];folder=self.root/key;folder.mkdir(exist_ok=True)
   if folder.is_symlink():raise ValueError('Unsafe alert directory')
   review_bounds=render_screenshot(frame,obs['box'],folder/'object.png')
   event=dict(schema=3,id=key,created_epoch=time.time(),detected_epoch=row['received_epoch'],generation=generation,sequence=row['sequence'],pts_seconds=pts,track=obs['proposed_track_id'],model=obs['model'],score=obs['scores']['anomalous'],bounds=review_bounds,detection_bounds=obs['box'],flag_source='model',human_confirmed=False,screenshots=['object.png','object-detail.png'],native_crop='native-object.png',native_crop_sha256=hashlib.sha256((folder/'native-object.png').read_bytes()).hexdigest(),screenshot_description='Uncropped original frame with a yellow box, plus the exact boxed region smoothly enlarged with bicubic interpolation to at least 1024 pixels on its longest side. Display smoothing does not add captured detail',classification='anomalous',scientific_qualification=False,persistence_seconds=pts-g['first'],grouped_observations=g['hits'])
   # Reserve cooldown before publishing readiness; a crash fails closed.
   self.last=time.time();atomic(self.root/'producer-state.json',dict(last_queued_epoch=self.last,event_id=key));atomic(folder/'event.json',event);self.groups=[];return 1
  return 0
