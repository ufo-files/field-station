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
 """One readable image: original scene and a labeled nearest-neighbor object inset."""
 image=Image.fromarray(frame).convert('RGB');w,h=image.size;x,y,bw,bh=map(int,bounds)
 if bw<=0 or bh<=0 or x<0 or y<0 or x+bw>w or y+bh>h:raise ValueError('Invalid native object bounds')
 canvas=Image.new('RGB',(1600,900),'#101820');draw=ImageDraw.Draw(canvas);font=ImageFont.load_default(size=24)
 scene=image.resize((1120,630),Image.Resampling.LANCZOS);canvas.paste(scene,(20,90));sx=1120/w;sy=630/h
 draw.rectangle((20+x*sx,90+y*sy,20+(x+bw)*sx,90+(y+bh)*sy),outline='#ffdc00',width=3)
 # Native object pixels remain unchanged in meaning; enlargement adds no detail.
 pad=max(4,round(max(bw,bh)*.25));box=(max(0,x-pad),max(0,y-pad),min(w,x+bw+pad),min(h,y+bh+pad))
 crop=image.crop(box);scale=min(420/crop.width,420/crop.height);zoom=crop.resize((round(crop.width*scale),round(crop.height*scale)),Image.Resampling.NEAREST);zx=1160+(420-zoom.width)//2;zy=90+(420-zoom.height)//2;canvas.paste(zoom,(zx,zy))
 draw.rectangle((zx+(x-box[0])*scale,zy+(y-box[1])*scale,zx+(x+bw-box[0])*scale,zy+(y+bh-box[1])*scale),outline='#ffdc00',width=3)
 draw.text((20,25),'MODEL-FLAGGED CANDIDATE - NOT HUMAN CONFIRMED',font=font,fill='white')
 draw.text((20,745),f'Original scene: {w} x {h} pixels; yellow box marks the candidate.',font=font,fill='white')
 draw.text((1160,535),f'Object: {bw} x {bh} native pixels',font=font,fill='white')
 draw.text((1160,575),'Enlarged pixels; no added detail',font=ImageFont.load_default(size=19),fill='white')
 draw.text((20,810),'One captured frame, shown with scene context and a zoomed inset.',font=font,fill='white')
 temporary=path.with_suffix('.tmp');canvas.save(temporary,format='PNG');temporary.replace(path)

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
   render_screenshot(frame,obs['box'],folder/'object.png')
   event=dict(schema=2,id=key,created_epoch=time.time(),detected_epoch=row['received_epoch'],generation=generation,sequence=row['sequence'],pts_seconds=pts,track=obs['proposed_track_id'],model=obs['model'],score=obs['scores']['anomalous'],bounds=obs['box'],flag_source='model',human_confirmed=False,screenshot='object.png',screenshot_description='1600 x 900 scene context with a marked object and nearest-neighbor zoom; no added detail',classification='anomalous',scientific_qualification=False,persistence_seconds=pts-g['first'],grouped_observations=g['hits'])
   # Reserve cooldown before publishing readiness; a crash fails closed.
   self.last=time.time();atomic(self.root/'producer-state.json',dict(last_queued_epoch=self.last,event_id=key));atomic(folder/'event.json',event);self.groups=[];return 1
  return 0
