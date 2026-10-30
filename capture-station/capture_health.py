"""Measure delivered frames from timestamps, separately from requested frame rate."""
import json
import math
import re
import threading
import time

FRAME = re.compile(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:([-\d.]+)')
OVERWRITE = re.compile(r'UFO_AVF_OVERWRITE total=(\d+)')

class CaptureHealth:
    def __init__(self, folder, nominal=60000/1001):
        self.folder=folder
        self.nominal=nominal
        self.lock=threading.Lock()
        self.first=None; self.last=None; self.last_write=0
        self.state=dict(captured_frames=0, requested_fps=nominal, measured_fps=0,
                        timestamp_gap_count=0, timestamp_gap_max_seconds=0,
                        inferred_missing_frames=0, overwritten_frames=0, device_dropped_frames=0, nonmonotonic_timestamps=0)
        self.file=None; self.bucket=None
        self.time_base=None
    def feed(self,line):
        with self.lock:
            base=re.search(r'config in time_base:\s*(\d+)/(\d+)',line)
            if base:self.time_base=int(base[1])/int(base[2])
            queued=re.search(r'UFO_AVF_QUEUE depth=(\d+) highwater=(\d+) capacity=(\d+)',line)
            if queued:self.state.update(input_queue_frames=int(queued[1]),input_queue_highwater_frames=int(queued[2]),input_queue_capacity_frames=int(queued[3]))
            overwritten=OVERWRITE.search(line)
            if overwritten:self.state['overwritten_frames']=int(overwritten[1])
            if 'UFO_AVF_DEVICE_DROP' in line:self.state['device_dropped_frames']+=1
            match=FRAME.search(line)
            if not match:return False
            number,pts,seconds=int(match[1]),int(match[2]),float(match[3])
            if self.time_base is not None:seconds=pts*self.time_base
            now=time.time()
            if self.first is None:self.first=seconds;self.state['first_frame_epoch']=now
            if self.last is not None:
                gap=seconds-self.last
                self.state['timestamp_gap_max_seconds']=max(self.state['timestamp_gap_max_seconds'],gap)
                if gap<=0:self.state['nonmonotonic_timestamps']+=1
                if gap>1.5/self.nominal:
                    self.state['timestamp_gap_count']+=1
                    self.state['inferred_missing_frames']+=max(0,round(gap*self.nominal)-1)
            self.last=seconds
            self.state['captured_frames']+=1
            count=self.state['captured_frames']
            self.state.update(last_frame_epoch=now,last_pts_seconds=seconds,
                              measured_fps=(count-1)/(seconds-self.first) if seconds>self.first else 0)
            # Sidecars preserve every delivered source-relative timestamp before
            # Matroska's millisecond quantization. No synthetic timestamps.
            bucket=math.floor(seconds)
            if bucket!=self.bucket:
                if self.file:self.file.close()
                self.file=(self.folder/f'frame-times-{bucket:09d}.jsonl').open('a')
                self.bucket=bucket
            self.file.write(json.dumps(dict(sequence=number,pts=pts,pts_seconds=seconds,received_epoch=now))+'\n')
            self.file.flush()
            if now-self.last_write>=1:
                self.last_write=now
                path=self.folder/'capture-health.json';temporary=path.with_suffix('.tmp')
                temporary.write_text(json.dumps(self.state));temporary.replace(path)
            return True
    def snapshot(self):
        with self.lock:return dict(self.state)
    def close(self):
        with self.lock:
            if self.file:self.file.flush();self.file.close();self.file=None
            path=self.folder/'capture-health.json';temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(self.state));temporary.replace(path)

def drain_camera_log(pipe,log,health):
    try:
        for line in iter(pipe.readline,b''):
            text=line.decode(errors='replace')
            if health.feed(text):continue
            if 'Parsed_showinfo' not in text:log.write(text);log.flush()
    finally:health.close();pipe.close()
