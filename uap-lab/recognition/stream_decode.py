"""Persistent isolated decoder with four acknowledged native-frame buffers."""
import json,struct,subprocess,sys,threading
from pathlib import Path
from multiprocessing import shared_memory
import numpy as np
class StreamDecoder:
 def __init__(self):
  self.memory=[];self.errors=[]
  try:
   for _ in range(4):self.memory.append(shared_memory.SharedMemory(create=True,size=1920*1080))
   self.process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('stream_decode_worker.py')),json.dumps([m.name for m in self.memory])],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  except BaseException:
   for memory in self.memory:memory.close();memory.unlink()
   raise
  def drain():
   for line in self.process.stderr:self.errors[:]=[*self.errors[-9:],line.decode(errors='replace').strip()]
  self.thread=threading.Thread(target=drain,daemon=True);self.thread.start()
 def read_exact(self,n):
  chunks=[]
  while n:
   chunk=self.process.stdout.read(n)
   if not chunk:raise ValueError('Decoder output interrupted: '+'; '.join(self.errors))
   chunks.append(chunk);n-=len(chunk)
  return b''.join(chunks)
 def send(self,data):self.process.stdin.write(data);self.process.stdin.flush()
 def frames(self,path,preview_interval=0):
  path=str(path);self.send(json.dumps(dict(path=path,preview_interval=preview_interval)).encode()+b'\n');index=0
  while True:
   size=struct.unpack('!I',self.read_exact(4))[0]
   if not 0<size<=8192:raise ValueError('Invalid decoder header size')
   header=json.loads(self.read_exact(size))
   if header.get('path')!=path:raise ValueError('Decoder source changed')
   if header.get('end'):
    if header['frames']!=index or not index:raise ValueError('Incomplete decoded segment')
    return
   slot=header['slot']
   if header['index']!=index or slot!=index%len(self.memory):raise ValueError('Decoder frame repeated, skipped or reordered')
   if header.get('preview_bytes'):
    if (header.get('preview_width'),header.get('preview_height'),header['preview_bytes'])!=(1280,720,1280*720*3):raise ValueError('Invalid display preview dimensions')
    header['preview_bgr']=np.frombuffer(self.read_exact(header['preview_bytes']),dtype=np.uint8).reshape(720,1280,3)
   yield np.ndarray((1080,1920),dtype=np.uint8,buffer=self.memory[slot].buf),header
   self.send(f'ack {slot}\n'.encode());index+=1
 def close(self):
  try:self.process.stdin.close()
  except OSError:pass
  try:self.process.wait(timeout=2)
  except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=5)
  self.thread.join(timeout=1);self.process.stdout.close();self.process.stderr.close()
  for memory in self.memory:memory.close();memory.unlink()
 def __enter__(self):return self
 def __exit__(self,*args):self.close()
