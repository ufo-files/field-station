"""On-demand short review clips; original recordings and archival MP4s stay intact."""
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from experiments import load,save,utc


def event_position(manifest,event,source='after'):
    start=manifest.get('started_epoch')
    detected=event.get('detected_epoch')
    if start is not None and detected is not None:
        value=float(detected)-float(start)
        if source=='before':value-=float(event.get('settings',{}).get('reference_seconds',.4))
        return max(0,value)
    markers=manifest.get('markers',[])
    return max(0,float(markers[0].get('elapsed_seconds',0))) if markers else 0


def clip_window(position,duration):
    duration=max(0,float(duration or 0));position=max(0,float(position))
    if duration:position=min(position,duration)
    start=max(0,position-3)
    if duration:start=min(start,max(0,duration-12))
    length=min(12,duration-start) if duration else 12
    return dict(start=start,duration=max(.1,length),event_seconds=max(0,position-start))


class ReviewVideo:
    def __init__(self,station,root,env):
        self.station=station;self.root=Path(root);self.env=env;self.jobs=queue.Queue(maxsize=16)
        self.states={};self.lock=threading.RLock()
        threading.Thread(target=self.work,daemon=True).start()
    def status(self,key):
        with self.lock:return self.states.get(key,dict(state='not_prepared'))
    def request(self,body):
        key=str(body.get('key',''));review=self.station.boxed_review
        spec=review.video_info(key)
        if spec.get('available'):return spec
        sid,eid,folder,_=review.paths(key)
        if not (folder/'video.mkv').is_file():raise ValueError('The recording is not finalized or its source video is unavailable')
        with self.lock:
            if self.states.get(key,{}).get('state') in ('queued','processing'):return review.video_info(key)
            if self.jobs.full():raise ValueError('Review video queue is full; try again shortly')
            self.states[key]=dict(state='queued');self.jobs.put_nowait(key)
        return review.video_info(key)
    def work(self):
        while not self.station.exiting.is_set():
            try:key=self.jobs.get(timeout=1)
            except queue.Empty:continue
            proc=None;temporary=None
            try:
                with self.lock:self.states[key]=dict(state='processing')
                sid,eid,folder,_,event=self.station.boxed_review.event(key)
                manifest=load(folder/'manifest.json',{})
                source=event.get('human_review',{}).get('source_frame') or event.get('annotation',{}).get('source_frame','after')
                duration=manifest.get('buffer_assembly',{}).get('seconds') or manifest.get('elapsed_seconds')
                window=clip_window(event_position(manifest,event,source),duration)
                if shutil.disk_usage(folder).free<200*1024**2:raise OSError('Not enough free space for a review clip')
                target=folder/f'review-{eid}.mp4';temporary=folder/f'review-{eid}-tmp.mp4'
                args=['nice','-n','15',__import__('os').environ.get('FFMPEG',str(self.root/'vendor/root/usr/bin/ffmpeg')),'-nostdin','-hide_banner','-loglevel','error','-y',
                    '-ss',str(window['start']),'-threads','1','-filter_threads','1','-lowres','1','-i',str(folder/'video.mkv'),
                    '-t',str(window['duration']),'-an','-vf','fps=15,setsar=1','-c:v','libx264','-threads','1',
                    '-preset','ultrafast','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(temporary)]
                with (folder/f'review-{eid}.log').open('w') as log:
                    proc=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=log,env=self.env)
                    deadline=time.monotonic()+180
                    while proc.poll() is None:
                        if self.station.exiting.wait(.25):raise OSError('Review clip preparation interrupted by restart')
                        if time.monotonic()>deadline:raise OSError('Review clip preparation timed out')
                    if proc.returncode or not temporary.is_file() or temporary.stat().st_size<1000:raise OSError('Review clip encoding failed')
                temporary.replace(target)
                save(folder/f'review-{eid}.json',dict(**window,created_at=utc(),width=960,height=540,fps=15))
                with self.lock:self.states[key]=dict(state='ready')
            except (OSError,ValueError,KeyError) as error:
                with self.lock:self.states[key]=dict(state='failed',error=str(error))
            finally:
                if proc and proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                if temporary:temporary.unlink(missing_ok=True)
                self.jobs.task_done()
