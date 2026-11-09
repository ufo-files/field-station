"""Recognize proven empty finalized tails without inventing analyzed frames."""
import hashlib,json,time
from pathlib import Path

def closed_empty_segment(folder,entry):
 folder=Path(folder);source=folder/entry['file']
 if not (folder/'closed.json').is_file() or entry.get('bytes')!=0 or entry.get('sha256')!=hashlib.sha256(b'').hexdigest():return False
 if source.parent!=folder or source.is_symlink() or not source.is_file() or source.stat().st_size!=0:return False
 return True

def record_empty_segment(folder,entry):
 from spool_events import atomic
 if not closed_empty_segment(folder,entry):raise ValueError('Source is not a proven empty closed segment')
 path=Path(folder)/(entry['file']+'.unavailable.json')
 if not path.exists():atomic(path,dict(reason='empty_finalized_capture_segment',source=entry,recorded_epoch=time.time(),analyzed=False,original_preserved=True))
 return path
