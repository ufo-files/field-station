"""Fast-SSD inspection media; annotations always read the unchanged native clip."""
import hashlib,json,os,re,subprocess,sys
from pathlib import Path

def media_dir(data,key):
 if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid detection')
 runtime=os.environ.get('XDG_RUNTIME_DIR')
 if not runtime:return Path(data).parent/'notifications/outbox'/key
 return Path(runtime)/'review-videos'/hashlib.sha256(str(Path(data)).encode()).hexdigest()[:16]/key

def native_path(data,key):
 if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid detection')
 folder=Path(data).parent/'notifications/outbox'/key
 try:event=json.loads((folder/'event.json').read_text())
 except (OSError,ValueError):event={}
 if event.get('kind')=='manual_recording':
  from manual_recordings import SID
  sid=event.get('manual_session_id','')
  if not SID.fullmatch(sid):raise ValueError('Invalid manual recording')
  session=Path(data).parent/'sessions'/sid;source=session/'video.mp4'
  if session.is_symlink() or source.is_symlink():raise ValueError('Unsafe manual recording')
  return source
 fast=media_dir(data,key)/'review.mp4'
 if fast.is_file() and not fast.is_symlink():return fast
 folder=Path(data).parent/'notifications/outbox'/key
 try:
  if json.loads((folder/'review-clip.json').read_text()).get('media_storage')=='runtime':return fast
 except (OSError,ValueError):pass
 return folder/'review.mp4'

def playback_path(data,key):
 preview=media_dir(data,key)/'playback.mp4'
 return preview if preview.is_file() and not preview.is_symlink() else native_path(data,key)

def frame_times(path):
 import av
 with av.open(str(path)) as source:
  return [float(p.pts*p.time_base) for p in source.demux(video=0) if p.size and p.pts is not None]

def build_preview(source,target,timeout=120,original_times=None):
 """Preserve dimensions, frame count and timestamps; reduce playback bandwidth."""
 ffmpeg=os.environ.get('FFMPEG','/opt/homebrew/bin/ffmpeg');temp=target.with_name('playback-building.mp4')
 base=[ffmpeg,'-v','error','-nostdin','-y','-i',str(source),'-map','0:v:0','-an','-fps_mode','passthrough','-enc_time_base','demux','-g','15','-bf','0','-pix_fmt','yuv420p']
 encoders=[['-c:v','libx264','-threads','2','-preset','veryfast','-crf','22']]
 if sys.platform=='darwin':encoders.insert(0,['-c:v','h264_videotoolbox','-b:v','6M','-realtime','1','-allow_sw','0'])
 for encoder in encoders:
  try:subprocess.run(base+encoder+['-movflags','+faststart',str(temp)],check=True,capture_output=True,timeout=timeout);break
  except subprocess.CalledProcessError:
   if encoder==encoders[-1]:raise
 original=frame_times(source) if original_times is None else original_times;preview=frame_times(temp)
 if not original or len(original)!=len(preview) or any(abs(a-b)>.003 for a,b in zip(original,preview)):raise ValueError('Playback preview changed frame timing')
 temp.replace(target)
 return dict(playback_frames_verified=True,playback_bytes=target.stat().st_size,native_bytes=Path(source).stat().st_size)

from contextlib import contextmanager
@contextmanager
def event_lease(folder):
 import fcntl
 path=Path(folder)/'review-build.lock'
 if Path(folder).is_symlink() or path.is_symlink():raise ValueError('Unsafe review lock path')
 if not path.parent.exists():yield True;return
 with path.open('a') as handle:
  try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:yield False;return
  yield True

def pin_segment(source,target):
 """Retain a segment for inspection even when its spool lives on another drive."""
 import errno,shutil
 try:os.link(source,target)
 except OSError as exc:
  if exc.errno!=errno.EXDEV:raise
  # The caller verifies the copied bytes against the recorded SHA-256 before use.
  shutil.copyfile(source,target)
