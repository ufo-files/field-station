"""Color display images from the exact detection frame; training crops stay immutable."""
import hashlib,json,os,queue,re,threading,time,uuid
from pathlib import Path
from PIL import Image,ImageDraw

_QUEUE=queue.Queue(maxsize=32)
_LOCK=threading.Lock()
_PENDING=set()
_RETRY={}
_WORKER=None


def read(path,default=None):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return default


def sources(folder,event):
 root=folder.parent.parent.parent
 from review_playback import native_path
 clip=read(folder/'review-clip.json',{})
 if clip.get('state')=='ready':
  native=native_path(root/'uap-lab',folder.name)
  if native.is_file():yield native,clip['event_time']
 generation=event.get('generation','')
 if not re.fullmatch(r'run-[a-f0-9]+',generation):return
 spool=root/'capture-spool'/generation
 hint=event.get('review_color_source')
 if hint:
  entries=[(hint.get('file',''),hint.get('pts_seconds'))]
 else:
  entries=[]
  try:
   with (spool/'segments-index.jsonl').open() as stream:
    for line in stream:
     entry=json.loads(line)
     if entry['start']>event['pts_seconds']+.003:break
     if entry['start']-.003<=event['pts_seconds']<=entry['end']+.003:
      entries.append((entry['file'],event['pts_seconds']-entry['start']))
  except (OSError,ValueError):return
 for name,pts in entries:
  if not re.fullmatch(r'segment-\d+\.mkv',name) or not isinstance(pts,(int,float)):continue
  for base in (spool,root/'notifications/evidence'/generation):
   path=base/name
   if path.is_file() and not path.is_symlink():yield path,pts


def exact_color(path,seconds,expected):
 import av,numpy as np
 with av.open(str(path)) as source:
  source.streams.video[0].codec_context.thread_count=1
  source.seek(max(0,int((seconds-.25)*1000000)))
  for frame in source.decode(video=0):
   t=float(frame.pts*frame.time_base)
   if t>seconds+.003:break
   if abs(t-seconds)>.003:continue
   gray=frame.to_ndarray(format='gray')
   if gray.shape!=expected.shape or not np.array_equal(gray,expected):raise ValueError('Detection pixels do not match source video')
   return Image.fromarray(frame.to_ndarray(format='rgb24'))
 raise ValueError('Exact detection timestamp unavailable')


def write_images(folder,image,bounds):
 x,y,w,h=map(int,bounds)
 if w<1 or h<1 or x<0 or y<0 or x+w>image.width or y+h>image.height:raise ValueError('Invalid review bounds')
 crop=image.crop((x,y,x+w,y+h));scale=max(1,1024/max(crop.size));detail=crop.resize((round(crop.width*scale),round(crop.height*scale)),Image.Resampling.BICUBIC)
 marked=image.copy();draw=ImageDraw.Draw(marked);draw.rectangle((x,y,x+w-1,y+h-1),outline='#101820',width=7);draw.rectangle((x+2,y+2,x+w-3,y+h-3),outline='#ffdc00',width=3)
 for name,im in [('color-frame.jpg',image),('color-object.jpg',marked),('color-detail.jpg',detail)]:
  target=folder/name;tmp=folder/(name+'.'+uuid.uuid4().hex+'.tmp')
  try:im.save(tmp,format='JPEG',quality=92,subsampling=0);tmp.replace(target)
  finally:tmp.unlink(missing_ok=True)


def build(folder):
 folder=Path(folder)
 if folder.is_symlink() or not (folder/'event.json').is_file():return False
 from review_playback import event_lease
 with event_lease(folder) as available:
  if not available:return False
  if (folder/'label-queue-dismissed.json').exists():return False
  if (folder/'color-detail.jpg').is_file():return True
  import numpy as np
  event=read(folder/'event.json',{});original=Image.open(folder/'source-frame.png').convert('RGB');pixels=np.asarray(original)
  if not np.array_equal(pixels[:,:,0],pixels[:,:,1]) or not np.array_equal(pixels[:,:,1],pixels[:,:,2]):image=original
  else:
   image=None
   for path,seconds in sources(folder,event):
    try:image=exact_color(path,seconds,pixels[:,:,0]);break
    except (OSError,ValueError):continue
   if image is None:return False
  write_images(folder,image,event['bounds'])
  # Keep a lossless replacement for a reviewed quick-label crop, with provenance.
  x,y,w,h=event['bounds'];crop=image.crop((x,y,x+w,y+h));target=folder/'color-native-object.png';tmp=target.with_suffix('.tmp');crop.save(tmp,format='PNG');tmp.replace(target)
  record=dict(event_id=folder.name,bounds=event['bounds'],original_crop_sha256=event.get('native_crop_sha256'),color_crop_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),verification='exact_detection_timestamp_and_grayscale_pixels',input_color_space='RGB')
  temp=folder/'color-review.tmp';temp.write_text(json.dumps(record));temp.replace(folder/'color-review.json')
  return True


def request(folder):
 global _WORKER
 folder=Path(folder)
 if (folder/'color-detail.jpg').is_file():return
 key=str(folder)
 with _LOCK:
  if key in _PENDING or time.monotonic()<_RETRY.get(key,0):return
  try:_QUEUE.put_nowait(folder)
  except queue.Full:return
  _PENDING.add(key)
  if _WORKER is None:
   def work():
    while True:
     target=_QUEUE.get();ok=False
     try:ok=build(target)
     except Exception:pass # Display fallback must never block review or inference.
     finally:
      with _LOCK:
       _PENDING.discard(str(target))
       if len(_RETRY)>4096:_RETRY.clear()
       if not ok:_RETRY[str(target)]=time.monotonic()+60
      _QUEUE.task_done()
   _WORKER=threading.Thread(target=work,daemon=True,name='color-review');_WORKER.start()
