"""Bounded RAM ring of native MJPEG/Matroska segments and lossless clip spooling."""
import csv
import json,hashlib
import io
import math
import os
from pathlib import Path
import secrets
import shutil
import threading
import time
from experiments import load, save


class RollingBuffer:
    def __init__(self, run, exiting, keep_seconds=12, root=None):
        self.root=Path(root or os.environ.get('CAPTURE_BUFFER_ROOT',f'/dev/shm/field-station-{os.getuid()}'))
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.durable=os.environ.get("CAPTURE_DURABLE_SPOOL")=="1"
        self._known=set();self._rf_stamp=None;self._last_cleanup=0;self._csv_offset=0
        self.exiting=exiting
        self.lock=threading.RLock()
        self.keep_seconds=keep_seconds
        self.max_bytes=1536*1024**2
        self.path=None
        self.segments=[]
        self.anchor=None
        self.active=None
        self.error=None
        self.generation=0
        self.worker=threading.Thread(target=self.work,daemon=True)
        self.worker.start()

    def new_run(self):
        with self.lock:
            if self.active:raise ValueError('Cannot reset the RAM buffer during a recording')
            if self.durable:
                previous=self.path or self.root/load(self.root/'active.json',{}).get('generation','missing')
                if previous.is_dir():save(previous/'closed.json',dict(closed_epoch=time.time()))
            for directory in ([] if self.durable else self.root.glob('run-*')):
                if directory.is_dir() and not directory.is_symlink():shutil.rmtree(directory)
            self.path=self.root/('run-'+secrets.token_hex(8));self.path.mkdir(mode=0o700)
            self.segments=[];self._known=set();self._rf_stamp=None;self._csv_offset=0;self.anchor=None;self.error=None;self.generation+=1
            if self.durable:
                save(self.path/"generation.json",dict(created_epoch=time.time(),width=1920,height=1080,segment_list_append=True))
                save(self.root/"active.json",dict(generation=self.path.name))
            return self.path

    def status(self):
        with self.lock:
            seconds=self.segments[-1]['end_epoch']-self.segments[0]['start_epoch'] if self.segments else 0
            return dict(available_seconds=round(seconds,2),retention_seconds=self.keep_seconds,
                bytes=sum(s['bytes'] for s in self.segments),ram_limit_bytes=None if self.durable else self.max_bytes,minimum_spool_retention_seconds=86400 if self.durable else None,unacknowledged_retained=self.durable,
                storage='durable SSD spool' if self.durable else 'RAM' if str(self.root).startswith('/dev/shm/') else 'bounded disk cache',error=self.error,ready=bool(self.segments))

    def ingest(self):
        with self.lock:
            if not self.path:return
            next_offset=self._csv_offset
            try:
                if self.durable and load(self.path/'generation.json',{}).get('segment_list_append'):
                    with (self.path/'segments.csv').open() as listing:
                        listing.seek(self._csv_offset);lines=[]
                        while True:
                            position=listing.tell();line=listing.readline()
                            if not line or not line.endswith('\n'):next_offset=position;break
                            lines.append(line)
                    rows=list(csv.reader(lines))
                else:rows=list(csv.reader(io.StringIO((self.path/'segments.csv').read_text())))
            except FileNotFoundError:return
            known=self._known if self.durable else {s['file'] for s in self.segments}
            for row in rows:
                if len(row)!=3:continue
                name=Path(row[0]).name
                if not name.startswith('segment-') or not name.endswith('.mkv'):continue
                if name in known:continue
                try:
                    start,end=float(row[1]),float(row[2]);file=self.path/name;stat=file.stat()
                except (ValueError,FileNotFoundError):continue
                if end<=start:continue
                # Deleted, expired rows can remain in FFmpeg's bounded CSV list.
                if self.segments and end<=self.segments[-1]['end']:continue
                observed_anchor=stat.st_mtime-end
                if self.anchor is None:self.anchor=observed_anchor
                elif abs(observed_anchor-self.anchor)>2:
                    # Clock synchronization after boot must also update the ring's UTC mapping.
                    shift=observed_anchor-self.anchor
                    self.anchor=observed_anchor
                    for existing in self.segments:
                        existing['start_epoch']+=shift
                        existing['end_epoch']+=shift
                segment=dict(file=name,start=start,end=end,start_epoch=self.anchor+start,
                             end_epoch=self.anchor+end,bytes=stat.st_size)
                if self.durable:
                    digest=hashlib.sha256()
                    with file.open('rb') as source:
                        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
                        os.fsync(source.fileno())
                    segment['sha256']=digest.hexdigest()
                    save(self.path/(name+'.json'),segment)
                    with (self.path/'segments-index.jsonl').open('a') as index:
                        index.write(json.dumps(segment)+'\n');index.flush();os.fsync(index.fileno())
                self.segments.append(segment);known.add(name)
                if self.active:self.copy_segment(segment)
            self._csv_offset=next_offset
            if self.segments:
                cutoff=self.segments[-1]['end_epoch']-self.keep_seconds
                total=sum(s['bytes'] for s in self.segments)
                while len(self.segments)>1 and (self.segments[0]['end_epoch']<cutoff or (not self.durable and total>self.max_bytes)):
                    old=self.segments.pop(0);total-=old['bytes']
                    if self.durable:continue
                    (self.path/old['file']).unlink(missing_ok=True)
                    for timing in self.path.glob('frame-times-*.jsonl'):
                        try:bucket=int(timing.stem.split('-')[-1])
                        except ValueError:continue
                        if bucket+1<self.segments[0]['start']-1:timing.unlink(missing_ok=True)

    def copy_segment(self,segment):
        active=self.active
        if segment['end_epoch']<=active['requested_start_epoch']:return
        if active.get('requested_end_epoch') is not None and segment['start_epoch']>=active['requested_end_epoch']:return
        if any(s['file']==segment['file'] for s in active['segments']):return
        folder=Path(active['folder']);destination=folder/'buffer-segments'/segment['file']
        temporary=destination.with_suffix('.tmp')
        shutil.copyfile(self.path/segment['file'],temporary)
        temporary.replace(destination)
        # Segment PTS may round to milliseconds; retain the native timestamp log
        # alongside each event, including buckets touching segment boundaries.
        for bucket in range(max(0,math.floor(segment['start'])-1),math.ceil(segment['end'])+1):
            source=self.path/f'frame-times-{bucket:09d}.jsonl'
            if source.is_file():shutil.copyfile(source,folder/'buffer-segments'/source.name)
        active['segments'].append(segment.copy())
        save(folder/'buffer-state.json',active)

    def begin(self,folder,start_epoch):
        with self.lock:
            if self.active:raise ValueError('A capture already owns the buffer')
            if not self.segments:raise ValueError('Camera buffer is warming up; retry shortly')
            earliest=self.segments[0]['start_epoch']
            start=max(start_epoch,earliest)
            (folder/'buffer-segments').mkdir()
            self.active=dict(folder=str(folder),requested_start_epoch=start,requested_end_epoch=None,
                             requested_prebuffer_start_epoch=start_epoch,segments=[],state='recording')
            try:
                for segment in self.segments:self.copy_segment(segment)
                save(folder/'buffer-state.json',self.active)
            except BaseException:
                self.active=None
                raise
            return dict(actual_start_epoch=start,available_pre_seconds=max(0,time.time()-start),
                        prebuffer_complete=earliest<=start_epoch)

    def finish(self,end_epoch,timeout=4):
        with self.lock:
            if not self.active:raise ValueError('No buffered recording')
            self.active['requested_end_epoch']=end_epoch
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.ingest()
            with self.lock:
                if self.active['segments'] and self.active['segments'][-1]['end_epoch']>=end_epoch:break
            if self.exiting.is_set():break
            time.sleep(.05)
        with self.lock:
            active=self.active
            active['state']='queued'
            active['tail_complete']=bool(active['segments'] and active['segments'][-1]['end_epoch']>=end_epoch)
            save(Path(active['folder'])/'buffer-state.json',active)
            self.active=None
            return active

    def abandon(self):
        with self.lock:self.active=None

    def work(self):
        while not self.exiting.wait(.1):
            try:
                self.ingest()
                if self.durable and self.path:
                    frame=load(Path(os.environ.get('RF_LIVE_PATH','/Volumes/UFO-Field/signal-spool/live.json')),{})
                    stamp=frame.get('timestamp')
                    if stamp and stamp!=self._rf_stamp:
                        epoch=time.time()
                        with (self.path/f'rf-{int(epoch//60):012d}.jsonl').open('a') as log:
                            log.write(json.dumps(dict(captured_epoch=epoch,spectrum=frame))+'\n');log.flush()
                        self._rf_stamp=stamp
                self.error=None
            except (OSError,ValueError) as error:self.error=str(error)
