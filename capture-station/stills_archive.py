"""Selected native JPEGs and a small, resumable GitHub evidence archive."""
import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from experiments import load, save, file_info, utc

SID=re.compile(r'[0-9TZ]+-[a-f0-9]{6}')
FRAME=re.compile(r'(?:export-[a-f0-9]{10}/)?(?:frame-[0-9]{9}|second-[0-9]{6})\.jpg')
MOTION=re.compile(r'motion-[a-f0-9]{16}-(?:before|after|boxed)\.jpg')

def select_existing(folder):
    """Commit a bounded index before any old exports can be removed."""
    frames=folder/'frames'
    if frames.is_symlink():raise ValueError('Unsafe frames directory')
    old=load(frames/'index.json',{})
    entries=old.get('frames',[])
    if not entries:
        entries=[dict(file=str(p.relative_to(frames))) for p in sorted(frames.glob('export-*/frame-*.jpg')) if p.is_file() and not p.is_symlink()]
    valid=[]
    for entry in entries:
        name=entry.get('file','');path=frames/name
        if FRAME.fullmatch(name) and path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(frames.resolve()):valid.append(entry)
    if not valid:return None
    selected=[]
    for i in sorted({0,len(valid)//2,len(valid)-1}):
        item=valid[i];name=f'frame-{len(selected):09d}.jpg';destination=frames/name
        if frames/item['file']!=destination:
            temporary=destination.with_suffix('.tmp');shutil.copyfile(frames/item['file'],temporary);temporary.replace(destination)
        selected.append(dict(file=name,video_time_seconds=item.get('video_time_seconds'),**file_info(destination)))
    index=dict(mode='selected',timing='Selected original JPEGs; no rescaling or recompression.',frames=selected)
    save(frames/'index.json',index)
    return index


def prune_old_exports(folder,index):
    """Only delete known JPEG export paths after a verified evidence push."""
    frames=folder/'frames'
    if frames.is_symlink():raise ValueError('Unsafe frame directory')
    keep={v['file'] for v in index['frames']}
    for entry in index['frames']:
        p=frames/entry['file']
        if not p.is_file() or p.is_symlink() or file_info(p)!=dict(bytes=entry['bytes'],sha256=entry['sha256']):raise ValueError('Selected still changed')
    remove=[]
    for p in frames.rglob('*'):
        name=str(p.relative_to(frames))
        if p.is_symlink():raise ValueError('Unsafe frame export link')
        if p.is_file() and FRAME.fullmatch(name) and name not in keep:remove.append(p)
        elif p.is_file() and re.fullmatch(r'export-[a-f0-9]{10}/packets\.sha256',name):remove.append(p)
    reclaimed=0
    for p in remove:reclaimed+=p.stat().st_size;p.unlink()
    for p in frames.glob('export-*'):
        if p.is_dir() and not any(p.iterdir()):p.rmdir()
    return reclaimed


class StillsArchive:
    def __init__(self,station,root,data,start=True):
        self.station,self.root,self.data=station,Path(root),Path(data)
        self.repo=self.root/'private/stills-git'
        self.receipts=self.root/'private/stills-receipts';self.receipts.mkdir(parents=True,exist_ok=True)
        self.phase='starting';self.error=None;self.last_success=None
        self.worker=threading.Thread(target=self.work,daemon=True)
        if start:self.worker.start()

    def status(self):
        return dict(phase=self.phase,error=self.error,last_success=self.last_success,url='https://github.com/ufo-files/station-stills')

    def git(self,*args):
        p=subprocess.run(['git','-C',str(self.repo),*args],capture_output=True,text=True,timeout=120)
        if p.returncode:raise OSError(p.stderr[-1000:] or p.stdout[-1000:])
        return p.stdout.strip()

    def tick(self):
        if not self.repo.joinpath('.git').is_dir():raise OSError('Stills repository is not configured')
        if not self.station.youtube.storage()['available']:self.phase='waiting_storage';return
        self.phase='publishing';prepared=[]
        for path in sorted(self.data.glob('*/manifest.json')):
            sid=path.parent.name
            if not SID.fullmatch(sid):continue
            with self.station.lock:
                m=load(path,{})
                if m.get('state') not in ('completed','interrupted'):continue
                if self.station.youtube.busy(sid):continue
                folder=path.parent
                if m.get('frames',{}).get('mode')!='selected':
                    index=select_existing(folder)
                    if index:
                        m['frame_export_mode']='selected'
                        m['frame_integrity']=dict(every_recorded_frame=False,selected_original_stills=True)
                        m['frames']=dict(state='completed',mode='selected',count=len(index['frames']),completed_at=utc())
                        m.setdefault('files',{})['frames/index.json']=file_info(folder/'frames/index.json')
                        save(path,m)
                index=load(folder/'frames/index.json',{})
                if m.get('frames',{}).get('state')!='completed' or index.get('mode')!='selected':continue
                dest=self.repo/'sessions'/sid;dest.mkdir(parents=True,exist_ok=True)
                # No credentials, upload jobs, or arbitrary files enter the public repo.
                names=['manifest.json','rf.jsonl','motion-events.json','rf-trigger-events.json']
                names += [p.name for p in folder.iterdir() if MOTION.fullmatch(p.name)]
                names += ['frames/index.json']+['frames/'+v['file'] for v in index['frames']]
                for name in names:
                    src=folder/name
                    if not src.is_file():continue
                    if src.is_symlink() or not src.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe still archive source')
                    if src.stat().st_size>50*1024**2:raise ValueError('Evidence file exceeds archive batch limit')
                    target=dest/name;target.parent.mkdir(parents=True,exist_ok=True)
                    if not target.exists() or file_info(src)!=file_info(target):shutil.copyfile(src,target)
                prepared.append((sid,index,(m.get('internet_archive',{}) if m.get('internet_archive',{}).get('verified_at') else m.get('youtube',{}))))
        self.git('add','--all')
        if self.git('status','--porcelain'):self.git('commit','-m','Archive selected station stills and RF evidence')
        self.git('push','origin','HEAD:main')
        head=self.git('rev-parse','HEAD')
        remote=self.git('ls-remote','origin','refs/heads/main').split()[0]
        if head!=remote:raise OSError('Remote evidence commit not confirmed')
        for sid,index,youtube in prepared:
            folder=self.data/sid
            save(self.receipts/(sid+'.json'),dict(commit=head,verified_at=time.time(),frames=index['frames']))
            # Existing full exports are redundant only after both destinations succeed.
            if youtube.get('verified_at') and time.time()>=youtube['verified_at']+3600:
                with self.station.lock:
                    if not self.station.youtube.busy(sid):prune_old_exports(folder,index)
        self.last_success=utc();self.phase='idle';self.error=None

    def work(self):
        while not self.station.exiting.is_set():
            try:self.tick()
            except Exception as error:self.error=str(error);self.phase='error'
            self.station.exiting.wait(60)

    def shutdown(self):
        if self.worker.is_alive():self.worker.join(timeout=5)
