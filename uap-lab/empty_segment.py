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

def closed_final_data_segment(folder,entry):
 folder=Path(folder)
 if not (folder/'closed.json').is_file():return False
 rows=[json.loads(line) for line in (folder/'segments-index.jsonl').read_text().splitlines()]
 usable=[e for e in rows if e.get('bytes',0)>0]
 return bool(usable and usable[-1]['file']==entry['file'] and usable[-1]['sha256']==entry['sha256'])

def verified_timing_tail(folder,entry):
 folder=Path(folder);p=folder/(entry['file']+'.timing-unavailable.json')
 if not p.is_file():return None
 audit=json.loads(p.read_text());source=folder/entry['file']
 if source.is_symlink() or source.parent!=folder or audit.get('source')!=entry or audit.get('analyzed') is not False or audit.get('frames',0)<=0:return None
 if not audit['last_verified_pts']<audit['first_unavailable_pts']<=audit['last_unavailable_pts']<=entry['end']+.05:return None
 if not closed_final_data_segment(folder,entry) or hashlib.sha256(source.read_bytes()).hexdigest()!=entry['sha256']:return None
 return audit
