"""Resume after a retired capture generation without claiming missing coverage."""
import json,time
from pathlib import Path

def recover_missing_generation(root,state,last_epoch):
 root=Path(root)
 if (root/state['generation']).is_dir():return None
 if not last_epoch:raise RuntimeError('Missing capture generation has no recovery timestamp')
 choices=[]
 for folder in root.glob('run-*'):
  try:
   with (folder/'segments-index.jsonl').open('rb') as index:
    offset=0
    for line in index:
     if not line.endswith(b'\n'):break
     row=json.loads(line);source=folder/row['file']
     if row.get('start_epoch',0)>=last_epoch and source.parent==folder and source.is_file() and not source.is_symlink():
      choices.append((row['start_epoch'],folder.name,offset,row['start']));break
     offset+=len(line)
  except FileNotFoundError:continue
 if not choices:raise RuntimeError('Waiting for available capture data after retired generation')
 epoch,generation,offset,pts=min(choices)
 result=dict(state)
 result['generation_recoveries']=[*state.get('generation_recoveries',[]),dict(from_generation=state['generation'],last_sequence=state.get('last_sequence'),to_generation=generation,resume_epoch=epoch,reason='source_generation_missing',epoch=time.time())]
 result.update(generation=generation,offset=offset,last_sequence=None,last_pts=None,coverage_start_pts=pts,coverage_first_sequence=None,tracks={},track_serial=0,intentionally_discarded_ranges=[])
 return result
