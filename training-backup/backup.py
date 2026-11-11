"""Versioned, verified frame-only training backups on the HQ external volume."""
import argparse,fcntl,hashlib,json,os,shlex,subprocess,time,shutil
from pathlib import Path
from PIL import Image
REMOTE_PLAN='''import json
from pathlib import Path
root=Path('/Volumes/UFO-Field/uap-lab');files=['email-reviews/']
for name in ['omitted-objects.json','omitted-videos.json','retired-objects.json','retired-videos.json','active-model.json']:
 if (root/name).is_file():files.append(name)
for folder in (root/'videos').iterdir():
 for name in ['video.json','annotations.json','training-excluded.json']:
  if (folder/name).is_file():files.append(str((folder/name).relative_to(root)))
 try:annotations=json.loads((folder/'annotations.json').read_text())
 except FileNotFoundError:continue
 for row in annotations:
  p=folder/row['image']
  if p.suffix.lower() not in ('.png','.jpg','.jpeg') or p.is_symlink() or not p.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe training image')
  if not p.is_file():raise ValueError('Missing annotated training image: '+str(p))
  files.append(str(p.relative_to(root)))
print(json.dumps(sorted(set(files))))
'''
def save(path,value):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)
def verify(root):
 examples=0;images=0;size=0;inventory={}
 for p in sorted(root.rglob('*')):
  if p.is_symlink():raise ValueError('Backup contains a symbolic link: '+str(p))
  if not p.is_file() or p.parent==root and p.name in ('backup-inventory.json','backup-receipt.json','backup-read.lock'):continue
  raw=p.read_bytes();inventory[str(p.relative_to(root))]=hashlib.sha256(raw).hexdigest();size+=len(raw)
  if p.suffix.lower() in ('.png','.jpg','.jpeg'):
   with Image.open(p) as image:image.verify()
   images+=1
 for p in (root/'email-reviews/examples').glob('*/review.json'):
  r=json.loads(p.read_text())
  if r.get('deleted'):continue
  crop=p.parent/'native-object.png'
  if inventory.get(str(crop.relative_to(root)))!=r['native_crop_sha256']:raise ValueError('Review crop checksum mismatch: '+str(p))
  if r.get('human_confirmed'):examples+=1
  color=p.parent/'color-review.json'
  if color.exists():
   c=json.loads(color.read_text())
   if inventory.get(str((p.parent/'color-native-object.png').relative_to(root)))!=c['color_crop_sha256']:raise ValueError('Color crop checksum mismatch')
 for p in (root/'videos').glob('*/annotations.json'):
  for a in json.loads(p.read_text()):
   image=p.parent/a['image']
   if not image.resolve().is_relative_to(p.parent.resolve()) or str(image.relative_to(root)) not in inventory:raise ValueError('Missing annotated frame')
   examples+=1
 return dict(examples=examples,images=images,bytes=size,files=len(inventory)),inventory

def run(root,helper,transport):
 if not Path('/Volumes/UFO-Work').is_mount() or not (Path('/Volumes/UFO-Work')/'.hq-review-volume').is_file():raise ValueError('HQ external backup volume is unavailable')
 root.mkdir(parents=True,exist_ok=True)
 with (root/'backup.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  status=root/'status.json';stamp=str(time.time_ns());stage=root/'staging';stage.mkdir(exist_ok=True)
  try:
   save(status,dict(state='planning',started_epoch=time.time()))
   result=subprocess.run(['/usr/bin/python3',str(helper),shlex.join(['/Users/ufo-field/ufo-field/venv/bin/python','-c',REMOTE_PLAN])],capture_output=True,text=True,check=True,timeout=120)
   files=json.loads(result.stdout)
   for name in files:
    p=Path(name)
    if p.is_absolute() or '..' in p.parts or '\n' in name:raise ValueError('Unsafe backup path')
   filelist=root/'files.txt';filelist.write_text('\n'.join(files)+'\n');latest=root/'current'
   command=['/opt/homebrew/bin/rsync','-ar','--timeout=300','--delete','--safe-links','--include=*/','--include=*.json','--include=*.png','--include=*.jpg','--include=*.jpeg','--exclude=*','--files-from='+str(filelist),'-e','/usr/bin/python3 '+str(transport)]
   # Daily source checksum audit; ordinary updates use mtime/size plus local verification.
   audit=root/'source-audit.json'
   audit_epoch=json.loads(audit.read_text()).get('verified_epoch',0) if audit.exists() else 0
   full_audit=time.time()-audit_epoch>=86400
   if full_audit:command+=['--checksum']
   if latest.exists():command+=['--link-dest='+str(latest.resolve())]
   command+=['field:/Volumes/UFO-Field/uap-lab/',str(stage)+'/']
   save(status,dict(state='copying',started_epoch=time.time()));subprocess.run(command,check=True,timeout=7200)
   save(status,dict(state='verifying',started_epoch=time.time()));summary,inventory=verify(stage)
   if summary['examples']==0:raise ValueError('Refusing to publish an empty training backup')
   if full_audit:save(audit,dict(verified_epoch=time.time()))
   previous=json.loads((latest/'backup-receipt.json').read_text()) if latest.exists() else {}
   if summary['examples']<previous.get('examples',0)*.9:raise ValueError('Training source lost more than 10% of examples; previous verified backup retained')
   if latest.exists() and json.loads((latest/'backup-inventory.json').read_text())==inventory:
    receipt=json.loads((latest/'backup-receipt.json').read_text());receipt.update(verified_epoch=time.time(),unchanged=True);save(status,receipt);shutil.rmtree(stage);return
   save(stage/'backup-inventory.json',inventory);receipt=dict(state='verified',verified_epoch=time.time(),snapshot=stamp,**summary)
   save(stage/'backup-receipt.json',receipt);snapshots=root/'snapshots';snapshots.mkdir(exist_ok=True);target=snapshots/stamp;stage.rename(target)
   link=root/'current.next';link.unlink(missing_ok=True);link.symlink_to(target);link.replace(latest);save(status,receipt)
   # Keep four recent snapshots plus one per day for 90 days. Never prune unverified snapshots.
   candidates=sorted([p for p in snapshots.iterdir() if p.name.isdigit() and (p/'backup-receipt.json').is_file()],key=lambda p:int(p.name),reverse=True);keep={p.name for p in candidates[:4]};days=set()
   for old in candidates:
    epoch=int(old.name)/1e9;day=time.strftime('%Y-%m-%d',time.gmtime(epoch))
    if time.time()-epoch<=90*86400 and day not in days:keep.add(old.name);days.add(day)
   for old in candidates:
    if old.name not in keep and old!=target:
     with (old/'backup-read.lock').open('a') as pin:
      try:fcntl.flock(pin,fcntl.LOCK_EX|fcntl.LOCK_NB)
      except BlockingIOError:continue
      shutil.rmtree(old)
  except Exception as exc:
   save(status,dict(state='retry_pending',error=str(exc),updated_epoch=time.time()));raise
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--helper',type=Path,default=Path('/Users/ufo-files-agent/field-migration/ssh-field.py'));a=p.parse_args();run(a.root,a.helper,Path(__file__).with_name('ssh_transport.py'))
