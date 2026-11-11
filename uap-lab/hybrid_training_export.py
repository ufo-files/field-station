"""Export bounded native crops of unreviewed detections; no video or label mutation."""
import hashlib,io,json,re,sys,tarfile
from pathlib import Path
from PIL import Image

def export(data,ids,output):
 if not isinstance(ids,list) or len(ids)>200:raise ValueError('Choose at most 200 detections')
 rows=[];data=Path(data)
 with tarfile.open(fileobj=output,mode='w|') as tar:
  def add(name,raw):
   info=tarfile.TarInfo(name);info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
  for key in dict.fromkeys(ids):
   if not re.fullmatch('[a-f0-9]{32}',key):continue
   reviewed=data/'email-reviews/examples'/key/'review.json'
   if reviewed.exists():continue
   folder=data.parent/'notifications/outbox'/key
   try:
    event=json.loads((folder/'event.json').read_text());p=folder/'native-object.png'
    if p.is_symlink() or p.stat().st_size>1024**2:continue
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=event['native_crop_sha256']:continue
    with Image.open(io.BytesIO(raw)) as image:
     image=image.convert('RGB');w,h=image.size;pixel=hashlib.sha256(f'{w}x{h}:RGB:'.encode()+image.tobytes()).hexdigest()
    if (w,h)!=tuple(event['bounds'][2:]):continue
    add(key+'.png',raw);rows.append(dict(id=key,sha256=event['native_crop_sha256'],pixel_sha256=pixel,native_width=w,native_height=h,generation=event['generation'],captured_epoch=event['detected_epoch'],bounds=event['bounds'],detection_bounds=event.get('detection_bounds',event['bounds'])))
   except (OSError,ValueError,KeyError):continue
  add('samples.json',json.dumps(rows).encode())
if __name__=='__main__':export(Path('/Volumes/UFO-Field/uap-lab'),json.loads(sys.argv[1]),sys.stdout.buffer)
