"""Transparent broadcast spectrum overlay matching the camera page's plots."""
import io,json,math,os,threading,time
from pathlib import Path
from urllib.request import urlopen
from PIL import Image,ImageDraw,ImageFont

WIDTH=340
HEIGHT=182
RIGHT=30
BOTTOM=26
FONT=Path(__file__).resolve().parents[1]/'uap-lab/static/fonts/IBMPlexMono-Regular.woff2'

def finite(value):
 return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

class SpectrumOverlay:
 def __init__(self):
  self.bright=False;self.font=ImageFont.truetype(str(FONT),20);self.small=ImageFont.truetype(str(FONT),18)
 def palette(self,frame):
  if frame is not None:
   w,h=frame.size
   box=(int(w*(1280-RIGHT-WIDTH)/1280),int(h*(720-BOTTOM-HEIGHT)/720),int(w*(1280-RIGHT)/1280),int(h*(720-BOTTOM)/720))
   pixels=list(frame.convert('RGB').crop(box).resize((32,16)).getdata())
   light=sum(.2126*r+.7152*g+.0722*b for r,g,b in pixels)/(255*len(pixels))
   if light>.65:self.bright=True
   elif light<.45:self.bright=False
  return (17,17,17,255) if self.bright else (255,255,255,255)
 def render(self,data,frame=None,now=None,standby=False):
  now=time.time() if now is None else now;ink=(155,201,140,255) if standby else self.palette(frame)
  data=data if isinstance(data,dict) else {}
  image=Image.new('RGBA',(600,322));draw=ImageDraw.Draw(image);receivers=data.get('receivers',{}) or {}
  def text(x,y,value,font=None,right=False):draw.text((x,y),value,font=font or self.font,fill=ink,anchor='rt' if right else 'lt')
  fresh=[]
  for index,role in enumerate(('narrow','wide')):
   row=receivers.get(role) or {};span=row.get('range_hz');values=row.get('maximum_db') or row.get('average_db');top=42+index*140
   valid=isinstance(span,(list,tuple)) and len(span)==2 and all(finite(x) for x in span) and span[1]>span[0] and isinstance(values,list) and bool(values)
   timestamp=row.get('timestamp');age=max(0,now-timestamp) if finite(timestamp) else None
   current=valid and age is not None and age<5;fresh.append(current)
   if not valid:
    text(0,top+50,('Narrow band' if index==0 else 'Wide band')+' · waiting for receiver');continue
   text(0,top+2,f'{span[0]/1e6:.0f}–{span[1]/1e6:.0f} MHz');text(600,top+2,'−40',right=True);text(600,top+114,'−100 dB',right=True)
   for y in (35,75,115):draw.line((0,top+y,599,top+y),fill=ink,width=2)
   points=[]
   for x in range(600):
    start=int(x*len(values)/600);end=max(start+1,int((x+1)*len(values)/600));bins=[v for v in values[start:end] if finite(v)]
    if not bins:
     if len(points)>1:draw.line(points,fill=ink,width=2)
     points=[];continue
    peak=max(bins);points.append((x,top+115-max(0,min(1,(peak+100)/60))*80))
   if len(points)>1:draw.line(points,fill=ink,width=2)
   if role=='wide' and span[0]<=1590e6<1610e6<=span[1]:
    left=(1590e6-span[0])/(span[1]-span[0])*600;right=(1610e6-span[0])/(span[1]-span[0])*600;center=(left+right)/2;label_x=max(0,min(center+16,460))
    draw.rectangle((left,top+35,right,top+115),fill=(*ink[:3],46 if self.bright else 77),outline=ink,width=1)
    draw.line([(center,top+35),(center,top+27),(label_x-4,top+17)],fill=ink,width=1);text(label_x,top+2,'1590–1610 MHz',self.small)
   if not current:text(0,top+114,('Last reading '+str(int(age))+'s ago' if age is not None else 'No timestamp')+' · reconnecting',self.small)
  text(0,0,'RF spectrum')
  text(600,0,'Both receivers live' if all(fresh) else 'One receiver reconnecting' if any(fresh) else 'Waiting for receivers',self.small,True)
  return image.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS)

class OverlayPipe:
 def __init__(self,rf_path,preview_url=None,camera=None):
  self.camera=camera;self.rf_path=Path(rf_path);self.preview_url=preview_url;self.stop=threading.Event();self.renderer=SpectrumOverlay();self.frame=self.renderer.render({}).tobytes();self.reader,self.writer=os.pipe()
 def start(self):
  self.render_thread=threading.Thread(target=self.refresh,daemon=True);self.write_thread=threading.Thread(target=self.write,daemon=True);self.render_thread.start();self.write_thread.start()
 def refresh(self):
  while not self.stop.is_set():
   try:data=json.loads(self.rf_path.read_text())
   except (OSError,ValueError):data={}
   frame=None;standby=False
   try:
    if self.camera:raw,standby=self.camera.current()
    else:
     with urlopen(self.preview_url,timeout=.5) as response:raw=response.read(8*1024*1024)
    frame=Image.open(io.BytesIO(raw));frame.load()
   except (OSError,ValueError):pass
   try:self.frame=self.renderer.render(data,frame,standby=standby).tobytes()
   except (TypeError,ValueError,KeyError,AttributeError):self.frame=self.renderer.render({}).tobytes()
   self.stop.wait(.5)
 def write(self):
  try:
   with os.fdopen(self.writer,'wb',buffering=0) as pipe:
    deadline=time.monotonic()
    while not self.stop.is_set():
     raw=memoryview(self.frame)
     while raw:
      written=pipe.write(raw)
      if not written:return
      raw=raw[written:]
     deadline+=.2;delay=deadline-time.monotonic()
     if delay<0:deadline=time.monotonic()
     else:self.stop.wait(delay)
  except (BrokenPipeError,OSError):pass
 def close(self):
  self.stop.set()
  try:os.close(self.reader)
  except OSError:pass
  if hasattr(self,'write_thread'):self.write_thread.join(timeout=2)
