"""Annotated display derivatives only. Dropping a display update never skips analysis."""
import json,struct,threading,time
from pathlib import Path
import cv2

class RecognitionPreview:
    def __init__(self,folder):
        self.folder=Path(folder);self.pending=None;self.condition=threading.Condition();self.stopping=False;self.rendered=0;self.replaced=0;self.error=None
        self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()
    def submit(self,image,objects,timing,generation,model):
        item=(image,objects,dict(timing),generation,model)
        with self.condition:
            self.replaced+=self.pending is not None;self.pending=item;self.condition.notify()
    def work(self):
        while True:
            with self.condition:
                while self.pending is None and not self.stopping:self.condition.wait()
                if self.pending is None:return
                item=self.pending;self.pending=None
            try:
                image,objects,timing,generation,model=item;image=image.copy();height,width=image.shape[:2];tags=[]
                for obj in objects:
                    label=obj.get('suggested_label','unknown')
                    if label in ('cloud','unknown'):continue
                    x,y,w,h=obj['box'];x=round(x*width/1920);y=round(y*height/1080);w=round(w*width/1920);h=round(h*height/1080)
                    text=('Anomalous match?' if label=='anomalous' else label.capitalize())+' · suggestion'
                    # OpenCV's Hershey font uses ASCII; keep readable on every station.
                    text=text.replace(' · ',' - ')
                    cv2.rectangle(image,(x,y),(x+w,y+h),(0,220,255),2)
                    size=cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,.55,1)[0];tx=max(0,min(x,width-size[0]-8));ty=max(size[1]+6,y-5)
                    cv2.rectangle(image,(tx,ty-size[1]-5),(tx+size[0]+6,ty+4),(10,15,20),-1);cv2.putText(image,text,(tx+3,ty),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,220,255),1,cv2.LINE_AA)
                    tags.append(dict(label=label,box=obj['box'],proposed_track_id=obj['proposed_track_id'],confirmed=False))
                ok,jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,85])
                if not ok:raise ValueError('Preview encoding failed')
                metadata=dict(generation=generation,sequence=timing['sequence'],pts_seconds=timing['pts_seconds'],source_received_epoch=timing['received_epoch'],published_epoch=time.time(),width=width,height=height,model=model,tags=tags,derivative=True,capture_control=False)
                raw=json.dumps(metadata).encode();target=self.folder/'preview.bin';temporary=self.folder/'preview.tmp';temporary.write_bytes(struct.pack('!I',len(raw))+raw+jpeg.tobytes());temporary.replace(target);self.rendered+=1;self.error=None
            except Exception as exc:self.error=str(exc)
    def status(self):return dict(rendered=self.rendered,replaced_display_updates=self.replaced,error=self.error,display_only=True)
    def close(self):
        with self.condition:self.stopping=True;self.condition.notify()
        self.thread.join(timeout=5)

def unpack(raw):
    if len(raw)<4:raise ValueError('Incomplete preview bundle')
    length=struct.unpack('!I',raw[:4])[0]
    if not 0<length<=1024*1024 or len(raw)<=length+4:raise ValueError('Invalid preview bundle')
    return json.loads(raw[4:4+length]),raw[4+length:]
