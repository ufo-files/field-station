"""Explicit, local-speaker playback of the owner's downloaded CE5 audio."""
import atexit,os,subprocess,threading
from pathlib import Path

class Player:
 def __init__(self,root):
  self.root=Path(root);self.lock=threading.RLock();self.process=None;self.error=None;self.track=None
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
   return self.status()

_player=None
_guard=threading.Lock()
def player(root):
 global _player
 with _guard:
  if _player is None:
   _player=Player(root);atexit.register(_player.set,False)
  return _player
