"""Every-native-frame motion analysis and asynchronous provisional capture requests.

This is candidate analysis, not per-frame model classification. The distinction is
explicit in status and in every provisional session. No frame sampling or queue
replacement is used in decoding/analysis. HTTP notifications may coalesce while
all original frames are already retained in the rolling buffer.
"""
import json,os,threading,time
from pathlib import Path
import cv2
import lab
from native_frames import NativeFrames
from native_motion import NativeMotion
from native_journal import NativeJournal

class NativeCapture:
    def __init__(self,monitor):
        self.monitor=monitor;self.stop=monitor.stop_event;self.pending=None;self.lock=threading.Lock()
        self.status=dict(phase='starting',analyzed_frames=0,analysis_kind='native_frame_motion',model_classified_frames=0,missing_frames=0,failures=0)
        self.folder=monitor.folder
        self.checkpoint=lab.read(self.folder/'native-analysis.json',{})
        self.status.update(self.checkpoint,phase='starting')
    def start(self):
        if os.environ.get("CAPTURE_DURABLE_SPOOL")!="1":threading.Thread(target=self.notifications,daemon=True).start()
        threading.Thread(target=self.analyze,daemon=True).start()
    def notifications(self):
        while not self.stop.wait(.25):
            with self.lock:pending=self.pending
            if pending is None:continue
            try:
                if time.time()-pending['frame_epoch']>=14:
                    self.status['capture_error']='Candidate expired before recording could start; evidence may be incomplete'
                    self.status['expired_notifications']=self.status.get('expired_notifications',0)+1
                    with self.lock:
                        if self.pending is pending:self.pending=None
                    continue
                result=self.monitor.station('/api/provisional/detection',pending)
                self.status.update(capture_session=result['session_id'],capture_error=None)
                with self.lock:
                    if self.pending is pending:self.pending=None
            except Exception as exc:self.status['capture_error']=str(exc)
    def analyze(self):
        root=os.environ.get('CAPTURE_BUFFER_ROOT',str(Path.home()/'Library/Caches/ufo-field/buffer'))
        durable=os.environ.get('CAPTURE_DURABLE_SPOOL')=='1'
        def committed(state):self.checkpoint=dict(state)
        journal=NativeJournal(root,self.folder,self.monitor,committed) if durable else None
        if journal:journal.start()
        total=self.checkpoint.get('analyzed_frames',0);run_count=0;started=None;last_notify=0;last_save=0;previous_generation=self.checkpoint.get('generation');previous_sequence=self.checkpoint.get('last_sequence');previous_pts=self.checkpoint.get('last_pts_seconds');max_gap=self.checkpoint.get('timestamp_gap_max_seconds',0);missing=self.checkpoint.get('missing_frames',0)
        work_seconds=event_seconds=persist_seconds=0.0
        while not self.stop.is_set():
            try:
                reader=NativeFrames(root,start_at_latest=not durable,checkpoint=self.checkpoint,decoder='gray');detector=NativeMotion()
                for image,timing,state in reader.threaded_frames(self.stop):
                    tick=time.perf_counter()
                    if started is None:started=time.monotonic()
                    seq=timing['sequence'];pts=timing['pts_seconds'];generation=state['generation']
                    if generation!=previous_generation:
                        detector=NativeMotion();previous_sequence=None;previous_pts=None
                        self.status['stream_restarts']=self.status.get('stream_restarts',0)+(1 if previous_generation else 0)
                        self.status['generation_first_sequence']=seq;self.status['generation_analyzed_frames']=0;self.status['generation_missing_frames']=0
                    elif previous_sequence is not None:
                        if seq<=previous_sequence:raise ValueError('Native frame sequence repeated or reversed')
                        gap=max(0,seq-previous_sequence-1);missing+=gap;self.status['generation_missing_frames']=self.status.get('generation_missing_frames',0)+gap
                    if previous_pts is not None:max_gap=max(max_gap,pts-previous_pts)
                    boxes,metrics=detector.update(image,pts)
                    previous_generation=generation;previous_sequence=seq;previous_pts=pts;total+=1;run_count+=1;self.status['generation_analyzed_frames']=self.status.get('generation_analyzed_frames',0)+1
                    work_seconds+=time.perf_counter()-tick
                    now=time.time();latency=now-timing['received_epoch']
                    self.status.update(phase='analyzing',analyzed_frames=total,missing_frames=missing,
                        generation=generation,last_sequence=seq,last_pts_seconds=pts,analyzed_epoch=now,
                        capture=state.get('capture'),decode_errors=state['decode_errors'],timestamp_errors=state['timestamp_errors'],
                        analyzed_fps=run_count/max(.001,time.monotonic()-started),analysis_seconds=time.perf_counter()-tick,
                        latency_seconds=latency,max_latency_seconds=max(latency,self.status.get('max_latency_seconds',0)),
                        timestamp_gap_max_seconds=max_gap,backlog_frames=state['backlog_frames'],backlog_seconds=state['backlog_seconds'],
                        decode_queue_frames=state.get('decode_queue_frames',0),candidate_count=len(boxes),global_change=metrics['global_change'],error=None)
                    if durable:
                        event_tick=time.perf_counter()
                        enabled=self.monitor.config.get('provisional_enabled',True)
                        self.status.update(journal.state,preservation='durable_spool',capture_error=None,journal_queue_frames=journal.pending.qsize())
                        journal.submit((timing,boxes if enabled else [],metrics if enabled else {},generation,self.monitor.model_id,dict(self.status)))
                        event_seconds+=time.perf_counter()-event_tick
                        self.status['stage_seconds']=dict(motion=work_seconds,journal_submit=event_seconds,elapsed=time.monotonic()-started)
                    if not durable and (boxes or metrics['global_change']) and now-last_notify>=.5 and self.monitor.config.get('provisional_enabled',True):
                        request=dict(frame_epoch=timing['received_epoch'],sequence=seq,generation=generation,boxes=boxes[:128],candidate_count=len(boxes),global_change=metrics['global_change'],model_id=self.monitor.model_id)
                        with self.lock:
                            if self.pending and self.pending['generation']==generation and now-self.pending['frame_epoch']<2:
                                request['onset_epoch']=self.pending.get('onset_epoch',self.pending['frame_epoch'])
                            self.pending=request
                        last_notify=now
                    if not durable and now-last_save>=1:
                        persist_tick=time.perf_counter()
                        persist_seconds+=time.perf_counter()-persist_tick
                        self.status['stage_seconds']=dict(motion=work_seconds,event_journal=event_seconds,checkpoint=persist_seconds,elapsed=time.monotonic()-started)
                        self.monitor.state['native_analysis']=dict(self.status)
                        path=self.folder/'native-analysis.json';temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(self.status));temporary.replace(path)
                        self.checkpoint=dict(self.status);last_save=now
            except Exception as exc:
                if journal and not journal.error and not self.stop.is_set():journal.flush()
                if not durable:self.checkpoint=dict(self.status,generation=previous_generation,last_sequence=previous_sequence)
                with (self.folder/'native-errors.jsonl').open('a') as log:log.write(json.dumps(dict(epoch=time.time(),error=str(exc),last_sequence=previous_sequence,analyzed_frames=total))+'\n')
                self.status.update(phase='error',error=str(exc),last_error=str(exc),last_error_epoch=time.time(),failures=self.status['failures']+1)
                print('Native analysis error:',str(exc),flush=True)
                self.monitor.state['native_analysis']=dict(self.status)
                self.stop.wait(1)
