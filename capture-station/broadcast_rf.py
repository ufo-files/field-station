"""Transparent broadcast spectrum overlay matching the camera page's plots."""
import io,json,math,os,threading,time
from pathlib import Path
from urllib.request import urlopen
from PIL import Image,ImageDraw,ImageFont

WIDTH=420
HEIGHT=204
RIGHT=30
BOTTOM=26
OUTPUT_WIDTH=1280
OUTPUT_HEIGHT=720
FONT=Path(__file__).resolve().parents[1]/'uap-lab/static/fonts/IBMPlexMono-Regular.woff2'

def finite(value):
 return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

class SpectrumOverlay:
 def __init__(self):
  self.bright=False;self.font=ImageFont.truetype(str(FONT),28);self.small=ImageFont.truetype(str(FONT),24)
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
  data=data if isinstance(data,dict) else {};receivers=data.get('receivers',{}) or {}
  image=Image.new('RGBA',(840,408));draw=ImageDraw.Draw(image)
  def text(x,y,value,font=None,right=False):draw.text((x,y),value,font=font or self.small,fill=ink,anchor='rt' if right else 'lt')
  fresh=[]
  for index,role in enumerate(('narrow','wide')):
   row=receivers.get(role) or {};span=row.get('range_hz');values=row.get('maximum_db') or row.get('average_db');top=48+index*178
   valid=isinstance(span,(list,tuple)) and len(span)==2 and all(finite(x) for x in span) and span[1]>span[0] and isinstance(values,list) and bool(values)
   timestamp=row.get('timestamp');age=max(0,now-timestamp) if finite(timestamp) else None
   current=valid and age is not None and age<5;fresh.append(current)
   if not valid:
    text(0,top+55,('Narrow band' if index==0 else 'Wide band')+' · waiting for receiver');continue
   text(0,top+2,f'{span[0]/1e6:.0f}–{span[1]/1e6:.0f} MHz');text(840,top+2,'−40 dB',right=True)
   for y in (42,86,130):draw.line((0,top+y,839,top+y),fill=ink,width=2)
   points=[]
   for x in range(840):
    start=int(x*len(values)/840);end=max(start+1,int((x+1)*len(values)/840));bins=[v for v in values[start:end] if finite(v)]
    if not bins:
     if len(points)>1:draw.line(points,fill=ink,width=2)
     points=[];continue
    peak=max(bins);points.append((x,top+130-max(0,min(1,(peak+100)/60))*88))
   if len(points)>1:draw.line(points,fill=ink,width=2)
   text(840,top+144,'−100 dB',right=True)
   if role=='wide' and span[0]<=1590e6<1610e6<=span[1]:
    left=(1590e6-span[0])/(span[1]-span[0])*840;right=(1610e6-span[0])/(span[1]-span[0])*840;center=(left+right)/2;label_x=max(0,min(center+20,580))
    draw.rectangle((left,top+42,right,top+130),fill=(*ink[:3],46 if self.bright else 77),outline=ink,width=1)
    draw.line([(center,top+42),(center,top+32),(label_x-4,top+22)],fill=ink,width=1);text(label_x,top+2,'1590–1610 MHz')
   if not current:text(0,top+144,('Last reading '+str(int(age))+'s ago' if age is not None else 'No timestamp')+' · reconnecting')
  text(0,0,'RF spectrum',self.font)
  text(840,2,'Both receivers live' if all(fresh) else 'One receiver reconnecting' if any(fresh) else 'Waiting for receivers',right=True)
  return image.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS)

class OverlayPipe:
 def __init__(self,rf_path,preview_url=None,camera=None,tags_url='http://127.0.0.1:8091/api/live/status'):
  from broadcast_tags import TagOverlay
  from broadcast_watermark import Watermark
  self.tags_url=tags_url;self.tags={};self.tag_renderer=TagOverlay();self.watermark=Watermark()
  self.camera=camera;self.rf_path=Path(rf_path);self.preview_url=preview_url;self.stop=threading.Event();self.renderer=SpectrumOverlay();self.frame=self.compose(self.renderer.render({}),True).tobytes();self.reader,self.writer=os.pipe()
 def compose(self,rf,standby=False,frame=None):
  canvas=Image.new('RGBA',(OUTPUT_WIDTH,OUTPUT_HEIGHT))
  self.watermark.draw(canvas,frame,standby)
  self.tag_renderer.draw(canvas,self.tags,time.time(),standby)
  if standby:ImageDraw.Draw(canvas).rectangle((OUTPUT_WIDTH-RIGHT-WIDTH-10,OUTPUT_HEIGHT-BOTTOM-HEIGHT-10,OUTPUT_WIDTH-RIGHT+10,OUTPUT_HEIGHT-BOTTOM+10),fill=(8,19,13,242),outline=(155,201,140,255),width=1)
  canvas.alpha_composite(rf,(OUTPUT_WIDTH-RIGHT-WIDTH,OUTPUT_HEIGHT-BOTTOM-HEIGHT))
  return canvas
 def poll_tags(self):
  while not self.stop.is_set():
   try:
    with urlopen(self.tags_url,timeout=.4) as response:data=json.loads(response.read(1024*1024))
    self.tags=data if isinstance(data,dict) else {}
   except (OSError,ValueError):self.tags={}
   self.stop.wait(.25)
 def start(self):
  self.tags_thread=threading.Thread(target=self.poll_tags,daemon=True);self.tags_thread.start()
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
   try:self.frame=self.compose(self.renderer.render(data,frame,standby=standby),standby,frame).tobytes()
   except (TypeError,ValueError,KeyError,AttributeError):self.frame=self.compose(self.renderer.render({}),True).tobytes()
   self.stop.wait(.2)
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
