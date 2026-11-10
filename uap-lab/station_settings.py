"""Private station preferences, persisted on the capture volume."""
import fcntl,time
from pathlib import Path
from retired_data import read,save
DELAYS=(10800,21600,43200,86400)

def settings(root):
 value=read(Path(root)/'station-settings.json',{})
 delay=value.get('after_seconds',10800)
 if type(delay) is not int or delay not in DELAYS:delay=10800
 return dict(daytime_auto_cleanup=value.get('daytime_auto_cleanup') is True,after_seconds=delay,timezone='America/Los_Angeles',daytime_only=True)

def policy(root):
 value=settings(root)
 return dict(enabled=value['daytime_auto_cleanup'],after_seconds=value['after_seconds'])

def update(root,value):
 if not isinstance(value,dict) or not value or set(value)-{'daytime_auto_cleanup','after_seconds'}:raise ValueError('Invalid cleanup settings.')
 if 'daytime_auto_cleanup' in value and type(value['daytime_auto_cleanup']) is not bool:raise ValueError('Choose whether daytime auto-cleanup is enabled.')
 if 'after_seconds' in value and (type(value['after_seconds']) is not int or value['after_seconds'] not in DELAYS):raise ValueError('Choose 3, 6, 12, or 24 hours.')
 root=Path(root)
 with (root/'station-settings.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  current=read(root/'station-settings.json',{})
  save(root/'station-settings.json',dict(current,**value,updated_epoch=time.time()))
 return settings(root)
