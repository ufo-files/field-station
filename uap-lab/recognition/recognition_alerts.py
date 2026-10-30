"""Durable anomaly notifications using the exact native crops already classified."""
import hashlib,json,os,re,time
from pathlib import Path

class AlertOutbox:
 def __init__(self,root,not_before=0):
  self.not_before=not_before
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
  self.seen=set(p.name for p in self.root.iterdir() if re.fullmatch('[a-f0-9]{32}',p.name) and (p/'event.json').is_file())
 def submit(self,generation,row,indices,crops):
  if row['received_epoch']<self.not_before:return 0
  if len(indices)!=len(crops):raise ValueError('Alert crops do not match classified observations')
  count=0
  for i,crop in zip(indices,crops):
   obs=row['observations'][i]
   if obs.get('suggested_label')!='anomalous':continue
   track=obs['proposed_track_id'];key=hashlib.sha256(f'{generation}:{track}'.encode()).hexdigest()[:32]
   if key in self.seen:continue
   folder=self.root/key;folder.mkdir(exist_ok=True)
   if folder.is_symlink():raise ValueError('Alert folder must not be a symlink')
   event=dict(schema=1,id=key,created_epoch=time.time(),detected_epoch=row['received_epoch'],generation=generation,sequence=row['sequence'],pts_seconds=row['pts_seconds'],track=track,model=obs['model'],score=obs['scores']['anomalous'],bounds=obs['box'],flag_source='model',human_confirmed=False,screenshot='object.png',screenshot_description='Exact native grayscale crop supplied to the classifier',classification='anomalous',scientific_qualification=False)
   # Metadata is the ready marker. A crash before it is written is replayable.
   for name,data in [('object.png',crop),('event.json',json.dumps(event,allow_nan=False).encode())]:
    temp=folder/(name+'.tmp')
    with temp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    temp.replace(folder/name)
   fd=os.open(folder,os.O_RDONLY)
   try:os.fsync(fd)
   finally:os.close(fd)
   self.seen.add(key);count+=1
  return count
