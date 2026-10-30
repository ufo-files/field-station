import json,struct,sys,time
from multiprocessing import shared_memory
import av,numpy as np
from av.codec.hwaccel import HWAccel
memories=[shared_memory.SharedMemory(name=n,track=False) for n in json.loads(sys.argv[1])]
slots=[np.ndarray((1080,1920),dtype=np.uint8,buffer=m.buf) for m in memories]
def emit(header):
 data=json.dumps(header).encode();sys.stdout.buffer.write(struct.pack('!I',len(data))+data);sys.stdout.buffer.flush()
def acknowledge(slot):
 if sys.stdin.buffer.readline()!=f'ack {slot}\n'.encode():raise ValueError('Invalid decoder acknowledgment')
last_preview=-float('inf')
try:
 for command in sys.stdin.buffer:
  request=json.loads(command);path=request['path'];preview_interval=float(request.get('preview_interval',0));count=0
  with av.open(path,hwaccel=HWAccel('videotoolbox',allow_software_fallback=False)) as container:
   stream=container.streams.video[0]
   if not stream.codec_context.is_hwaccel:raise ValueError('Required VideoToolbox decoder unavailable')
   stream.codec_context.thread_count=2;stream.codec_context.thread_type='FRAME';stream.codec_context.skip_frame='NONE'
   for frame in container.decode(stream):
    if frame.pts is None or frame.time_base is None or (frame.width,frame.height)!=(1920,1080):raise ValueError('Invalid native frame geometry or PTS')
    slot=count%len(slots)
    if count>=len(slots):acknowledge(slot)
    slots[slot][:]=frame.to_ndarray(format='gray')
    header=dict(path=path,index=count,pts_seconds=float(frame.pts*frame.time_base),slot=slot,hardware_decode=True)
    preview=None
    if preview_interval>0 and time.monotonic()-last_preview>=preview_interval:
     preview=frame.reformat(width=1280,height=720,format='bgr24').to_ndarray().tobytes();last_preview=time.monotonic();header.update(preview_bytes=len(preview),preview_width=1280,preview_height=720)
    emit(header)
    if preview is not None:sys.stdout.buffer.write(preview);sys.stdout.buffer.flush()
    count+=1
  for index in range(max(0,count-len(slots)),count):acknowledge(index%len(slots))
  emit(dict(end=True,path=path,frames=count))
finally:
 for memory in memories:memory.close()
