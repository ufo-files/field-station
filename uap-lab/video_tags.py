"""Session-scoped custom tags shared by all detections from a recording."""
import sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'shared'))
from archive_tags import BASE,normalize
from ce5_history import overlap
from video_trim import session_for

def status(data,key):
 import lab
 try:folder=session_for(data,key)
 except ValueError:return dict(available=False)
 root=Path(data).parent;value=lab.read(root/'archive-tags'/(folder.name+'.json'),{})
 manifest=lab.read(folder/'manifest.json',{})
 automatic=[*BASE,*(['ce5-tones'] if overlap(root,manifest) else [])]
 receipt=lab.read(root/'archive-tags'/('status-'+folder.name+'.json'),{})
 return dict(available=True,session_id=folder.name,automatic=automatic,custom=value.get('tags',[]),revision=value.get('revision'),archive_sync=receipt.get('state') if receipt.get('revision')==value.get('revision') else 'pending' if value.get('revision') else None)

def save(data,body):
 import lab
 folder=session_for(data,body.get('id',''));tags=normalize(body.get('tags'))
 target=Path(data).parent/'archive-tags'/(folder.name+'.json')
 target.parent.mkdir(parents=True,exist_ok=True)
 import fcntl
 with (target.parent/(folder.name+'.lock')).open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  previous=lab.read(target,{})
  if body.get('revision')!=previous.get('revision'):raise ValueError('Tags changed in another window. Reload before saving your changes.')
  lab.save(target,dict(tags=tags,revision=uuid.uuid4().hex,saved_epoch=time.time()))
 return dict(saved=True,**status(data,body['id']))
