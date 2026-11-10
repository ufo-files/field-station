"""Private station preferences, persisted on the capture volume."""
import fcntl,time
from pathlib import Path
from retired_data import read,save

def settings(root):
 value=read(Path(root)/'station-settings.json',{})
 return dict(daytime_auto_cleanup=value.get('daytime_auto_cleanup') is True,after_seconds=10800,timezone='America/Los_Angeles',daytime_only=True)

def policy(root):
 return dict(enabled=settings(root)['daytime_auto_cleanup'],after_seconds=10800)

def update(root,value):
 if not isinstance(value,dict) or set(value)!={'daytime_auto_cleanup'} or type(value['daytime_auto_cleanup']) is not bool:raise ValueError('Choose whether daytime auto-cleanup is enabled.')
 root=Path(root)
 with (root/'station-settings.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  current=read(root/'station-settings.json',{})
  save(root/'station-settings.json',dict(current,**value,updated_epoch=time.time()))
 return settings(root)
