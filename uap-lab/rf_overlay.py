"""Read-only local spectrum data for the browser overlay; never opens a receiver."""
import json,os,time
from pathlib import Path

def snapshot(path=None):
    path=Path(path or os.environ.get('RF_LIVE_PATH','/Volumes/UFO-Field/signal-spool/live.json'))
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):return dict(receivers={},available=False,local_hour=time.localtime().tm_hour)
    receivers={}
    for role in ('narrow','wide'):
        row=data.get('receivers',{}).get(role)
        if not isinstance(row,dict):continue
        receivers[role]={key:row.get(key) for key in ('timestamp','range_hz','average_db','maximum_db')}
    return dict(receivers=receivers,available=bool(receivers),server_epoch=time.time(),local_hour=time.localtime().tm_hour)
