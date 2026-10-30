"""Sequential decoding of completed native capture segments; gaps are explicit.

The JPEG preview is never an inference source. A bounded rolling buffer can expire
if analysis falls behind; that is an error with counted missing frames, not a
license to report skipped frames as analyzed.
"""
import csv,json,math,time,queue,threading,subprocess,os,tempfile,re,bisect
import numpy as np
from pathlib import Path
import cv2

def timing_rows(folder,start,end):
    rows=[]
    for bucket in range(max(0,math.floor(start)-1),math.ceil(end)+1):
        path=folder/f'frame-times-{bucket:09d}.jsonl'
        try:lines=path.read_text().splitlines()
        except FileNotFoundError:continue
        for line in lines:
            try:row=json.loads(line)
            except ValueError:continue
            pts=row['pts_seconds']
            # Matroska segment boundaries are rounded to the nearest millisecond.
            if start-.025<=pts<end+.025:rows.append(row)
    return sorted(rows,key=lambda r:r['sequence'])

class GrayDecoder:
    """Direct native decode with original container PTS; no frame-rate conversion."""
    def __init__(self,path):
        import av
        self.container=av.open(str(path));self.stream=self.container.streams.video[0]
        self.stream.codec_context.thread_count=2;self.stream.codec_context.thread_type='FRAME';self.stream.codec_context.skip_frame='NONE'
        self.iterator=self.container.decode(self.stream);self.pts_seconds=None
    def read(self):
        try:frame=next(self.iterator)
        except StopIteration:return False,None
        if frame.pts is None or frame.time_base is None:raise ValueError('Decoded frame has no original timestamp')
        if frame.width!=1920 or frame.height!=1080:raise ValueError('Unexpected native capture dimensions')
        self.pts_seconds=float(frame.pts*frame.time_base)
        return True,frame.to_ndarray(format='gray')
    def release(self):self.container.close()

class NativeFrames:
    def __init__(self,root,start_at_latest=False,checkpoint=None,decoder="opencv"):
        self.decoder=decoder;self.root=Path(root);self.run=None;self.next_segment=None;self.last_sequence=None
        self.start_at_latest=start_at_latest;self.checkpoint=checkpoint or {};self.finished_runs=set()
        self.index_offset=0;self.index_rows=[];self.index_numbers=[]
        self.state=dict(decoded_frames=0,missing_frames=0,decode_errors=0,timestamp_errors=0,
                        stream_restarts=0,backlog_frames=0,backlog_seconds=0)
    def threaded_frames(self,stop):
        pending=queue.Queue(maxsize=4);producer_stop=threading.Event()
        def deliver(item):
            while not stop.is_set() and not producer_stop.is_set():
                try:pending.put(item,timeout=.1);return
                except queue.Full:continue
        def produce():
            try:
                for item in self.frames(producer_stop):
                    if stop.is_set():break
                    deliver(item)
            except Exception as exc:deliver(exc)
        thread=threading.Thread(target=produce,daemon=True);thread.start()
        try:
            while not stop.is_set():
                try:item=pending.get(timeout=.1)
                except queue.Empty:continue
                if isinstance(item,Exception):raise item
                image,timing,state=item
                state['decode_queue_frames']=pending.qsize()
                yield image,timing,state
        finally:
            producer_stop.set();thread.join(timeout=2)
    def frames(self,stop):
        while not stop.is_set():
            runs=sorted(self.root.glob('run-*'),key=lambda p:p.stat().st_mtime)
            if not runs:stop.wait(.05);continue
            durable=[r for r in runs if (r/'generation.json').exists()]
            if durable:
                durable.sort(key=lambda r:json.loads((r/'generation.json').read_text())['created_epoch'])
                pending=[r for r in durable if r.name not in self.finished_runs and not (r/'analysis-complete.json').exists()]
                if not pending:stop.wait(.05);continue
                folder=pending[0]
            else:folder=runs[-1]
            if folder!=self.run:
                if self.run is not None:self.state['stream_restarts']+=1
                self.index_offset=0;self.index_rows=[];self.index_numbers=[]
                self.run=folder;self.next_segment=None;self.last_sequence=self.checkpoint.get("last_sequence") if folder.name==self.checkpoint.get("generation") else None
                self.state.update(generation=folder.name,decoded_frames=0,missing_frames=0,timestamp_errors=0,decode_errors=0)
            try:
                if (folder/'generation.json').exists():
                    with (folder/'segments-index.jsonl').open() as f:
                        f.seek(self.index_offset)
                        while True:
                            position=f.tell();line=f.readline()
                            if not line or not line.endswith('\n'):self.index_offset=position;break
                            entry=json.loads(line);self.index_rows.append([entry['file'],entry['start'],entry['end']]);self.index_numbers.append(int(Path(entry['file']).stem.split('-')[-1]))
                    segments=self.index_rows
                else:
                    with (folder/'segments.csv').open() as f:segments=list(csv.reader(f))
            except FileNotFoundError:stop.wait(.02);continue
            available=[]
            upcoming=segments[bisect.bisect_left(self.index_numbers,self.next_segment or 0):] if self.index_numbers else segments
            for row in upcoming:
                if len(row)!=3:continue
                name,start,end=row
                number=int(Path(name).stem.split('-')[-1])
                if self.next_segment is None or number>=self.next_segment:
                    if (folder/Path(name).name).is_file():
                        available.append((number,Path(name).name,float(start),float(end)))
                        if durable:break
            if not available:
                if (folder/'closed.json').exists() and segments and self.next_segment is not None:
                    # Completed-run marker is diagnostic, not a deletion acknowledgment.
                    (folder/'decode-complete.json').write_text(json.dumps(dict(last_sequence=self.last_sequence)))
                    self.finished_runs.add(folder.name)
                stop.wait(.01);continue
            number,name,start,end=max(available) if self.next_segment is None and self.start_at_latest and self.last_sequence is None and not durable else min(available)
            if self.next_segment is not None and number!=self.next_segment:
                self.state['decode_errors']+=1
            rows=timing_rows(folder,start,end)
            resume_sequence=self.checkpoint.get('last_sequence',-1) if folder.name==self.checkpoint.get('generation') else -1
            if rows and rows[-1]['sequence']<=resume_sequence:
                self.next_segment=number+1;continue
            cap=GrayDecoder(folder/name) if self.decoder=='gray' else cv2.VideoCapture(str(folder/name),cv2.CAP_FFMPEG,[cv2.CAP_PROP_N_THREADS,1])
            index=0;matched=[];pts_values=[r["pts_seconds"] for r in rows]
            try:health=json.loads((folder/'capture-health.json').read_text())
            except (OSError,ValueError):health={}
            try:
                while not stop.is_set():
                    ok,image=cap.read()
                    if not ok:break
                    if self.decoder=='gray':
                        global_pts=start+cap.pts_seconds
                        nearest=bisect.bisect_left(pts_values,global_pts)
                        options=[i for i in (nearest-1,nearest) if 0<=i<len(rows)]
                        choice=min(options,key=lambda i:abs(pts_values[i]-global_pts)) if options else None
                        if choice is None or abs(pts_values[choice]-global_pts)>.003:
                            self.state['timestamp_errors']+=1;raise ValueError('Decoded PTS has no matching original timestamp')
                        timing=rows[choice]
                    else:
                        exact=[r for r in rows if start<=r['pts_seconds']+.0005<end]
                        if index>=len(exact):raise ValueError('Native frame has no matching source timestamp')
                        timing=exact[index]
                    index+=1;sequence=timing['sequence'];matched.append(sequence)
                    if sequence<=resume_sequence:continue
                    if 'first_sequence' not in self.state:self.state['first_sequence']=sequence
                    if self.last_sequence is not None:
                        if sequence<=self.last_sequence:raise ValueError('Repeated or reversed native sequence')
                        self.state['missing_frames']+=max(0,sequence-self.last_sequence-1)
                    else:self.state['first_sequence']=sequence
                    self.last_sequence=sequence
                    self.state['decoded_frames']+=1
                    self.state['last_sequence']=sequence
                    self.state['last_pts_seconds']=timing['pts_seconds'];self.state['segment']=name
                    self.state['backlog_seconds']=max(0,float(segments[-1][2])-timing['pts_seconds'])
                    self.state['capture']=health
                    self.state['backlog_frames']=max(0,health.get('captured_frames',sequence+1)-sequence-1)
                    yield image,timing,dict(self.state)
                if len(matched)!=len(set(matched)) or (self.decoder!='gray' and index!=len(exact)):
                    self.state['decode_errors']+=1
                    raise ValueError(f'Decoded {index} frames for {len(rows)} native timestamps')
            finally:cap.release()
            self.next_segment=number+1
