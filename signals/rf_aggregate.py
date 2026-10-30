"""Keep both receiver snapshots and their independent UTC timestamps in event RF logs."""
import json,os,time
from pathlib import Path
root=Path(os.environ['RF_LIVE_PATH']).parent
while True:
 receivers={}
 for role in ['narrow','wide']:
  try:
   v=json.loads((root/role/'live.json').read_text());v['fresh']=0<=time.time()-v['timestamp']<5;receivers[role]=v
  except (OSError,ValueError,KeyError):pass
 if 'narrow' in receivers:
  result=dict(receivers['narrow'],receivers=receivers)
  tmp=root/'live.tmp';tmp.write_text(json.dumps(result,separators=(',',':')));tmp.replace(root/'live.json')
 time.sleep(.5)
