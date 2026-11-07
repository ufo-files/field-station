"""Explicit, local-speaker playback of the owner's downloaded CE5 audio."""
import atexit,os,subprocess,threading,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'shared'))
import ce5_history

class Player:
 def __init__(self,root):
  self.root=Path(root);self.lock=threading.RLock();self.process=None;self.error=None;self.track=None;self.playback_id=None
 def watch(self,process,identity):
  while True:
   time.sleep(1)
   with self.lock:
    if self.process is not process or process.poll() is not None:return
    try:ce5_history.observed(self.root,identity,time.time())
    except Exception:
     self.error='CE5 playback history could not be saved. Playback stopped.'
     process.terminate();self.process=None;return
 def source(self):
  configured=os.environ.get('CE5_AUDIO_FILE')
  if configured:
   path=Path(configured)
   return path if path.is_file() else None
  for name in ('audio/ce5.mp3','audio/ce5.wav','experiment-audio/ce5.wav'):
   path=self.root/name
   if path.is_file():return path
  uploads=self.root/'Uploads'
  if uploads.is_dir():
   tracks=[p for p in uploads.rglob('*') if p.suffix.lower() in {'.mp3','.wav','.m4a','.aiff','.flac'} and p.is_file() and p.resolve().is_relative_to(uploads.resolve())]
   if tracks:return min(tracks,key=lambda p:('WGT-CD3' not in str(p),str(p)))
  return None
 def status(self):
  with self.lock:
   if self.process is not None and self.process.poll() is not None:
    if self.process.returncode:self.error='CE5 playback stopped unexpectedly. Check the station audio output.'
    self.process=None
   source=self.track if self.process else self.source()
   return dict(playing=self.process is not None,available=source is not None,track=source.name if source else None,error=self.error)
 def set(self,enabled):
  if not isinstance(enabled,bool):raise ValueError('Choose whether CE5 Tones are enabled.')
  with self.lock:
   current=self.status()
   if not enabled:
    if self.process:
     if self.playback_id is not None:ce5_history.observed(self.root,self.playback_id,time.time())
     self.process.terminate()
     try:self.process.wait(timeout=2)
     except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
    self.process=None;self.error=None;return self.status()
   if current['playing']:return current
   source=self.source()
   if source is None:raise ValueError('The downloaded CE5 audio is not available on the station yet.')
   self.error=None;self.track=source
   # Playback uses the Mac's selected output without changing system volume.
   self.process=subprocess.Popen(['/usr/bin/afplay','-v','0.35',str(source)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   try:self.playback_id=ce5_history.begin(self.root,source,time.time())
   except Exception:
    self.process.terminate();self.process.wait(timeout=2);self.process=None;raise
   threading.Thread(target=self.watch,args=(self.process,self.playback_id),daemon=True).start()
   return self.status()

_player=None
_guard=threading.Lock()
def player(root):
 global _player
 with _guard:
  if _player is None:
   _player=Player(root);atexit.register(_player.set,False)
  return _player
