"""Ordered, bounded evidence writer. Analysis never acknowledges unwritten events."""
import json,queue,threading,time
from pathlib import Path
import lab
from spool_events import SpoolEvents,atomic

def finalized_end_pts(folder,entries):
    import av,hashlib
    entry=max(entries,key=lambda e:e['start']);path=folder/entry['file']
    if path.parent!=folder or path.is_symlink():raise ValueError('Unsafe finalized segment')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Finalized segment checksum mismatch')
    last=None
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            if frame.pts is None:raise ValueError('Finalized frame missing PTS')
            last=entry['start']+float(frame.pts*frame.time_base)
    if last is None:raise ValueError('Empty finalized segment')
    return last

class NativeJournal:
    def __init__(self,root,folder,monitor,checkpoint_callback,capacity=512):
        self.root=Path(root);self.folder=folder;self.monitor=monitor;self.stop=monitor.stop_event
        self.callback=checkpoint_callback;self.pending=queue.Queue(capacity);self.events=SpoolEvents(root)
        self.committed=lab.read(folder/'native-analysis.json',{})
        self.previous=dict(self.committed) if self.committed.get('generation') else None;self.error=None;self.last_save=0;self.write_seconds=0;self.state={}
    def start(self):threading.Thread(target=self.work,daemon=True).start()
    def submit(self,record):
        while not self.stop.is_set():
            if self.error:raise RuntimeError(self.error)
            try:self.pending.put(record,timeout=.1);return
            except queue.Full:continue
        raise RuntimeError(self.error or 'Evidence journal stopping')
    def flush(self):
        barrier=threading.Event();self.submit(('barrier',barrier))
        while not barrier.wait(.1):
            if self.error or self.stop.is_set():raise RuntimeError(self.error or 'Evidence journal stopping')
    def persist(self):
        if self.previous is None:return
        state=dict(self.previous);started=time.perf_counter()
        self.events.acknowledge(state['generation'],state)
        self.write_seconds+=time.perf_counter()-started
        state.update(journal_queue_frames=self.pending.qsize(),journal_write_seconds=self.write_seconds,journal_committed_epoch=time.time(),journal_lag_seconds=max(0,time.time()-state['analyzed_epoch']))
        atomic(self.folder/'native-analysis.json',state)
        self.committed=dict(state);self.monitor.state['native_analysis']=state;self.callback(state);self.last_save=time.monotonic()
    def process(self,record):
        timing,boxes,metrics,generation,model_id,state=record
        started=time.perf_counter()
        if self.previous and generation!=self.previous['generation']:
            prior=self.root/self.previous['generation'];health=lab.read(prior/'capture-health.json',{})
            if (prior/'closed.json').exists():
                captured=health.get('captured_frames')
                if self.previous['last_sequence']+1!=captured:
                    # A reboot can leave an unfinalized tail outside the immutable index.
                    # Advance only after all finalized video has actually been analyzed.
                    entries=[json.loads(line) for line in (prior/'segments-index.jsonl').read_text().splitlines()]
                    last_pts=self.previous.get('last_pts_seconds',-1)
                    if not entries or not isinstance(captured,int) or captured<=self.previous['last_sequence'] or abs(finalized_end_pts(prior,entries)-last_pts)>.003:
                        raise ValueError('Closed capture has delivered frames not acknowledged by analysis')
                    missing=captured-self.previous['last_sequence']-1
                    self.previous=dict(self.previous,generation_missing_frames=self.previous.get('generation_missing_frames',0)+missing,capture_unfinalized_tail_frames=missing)
                    atomic(prior/'capture-tail-unavailable.json',dict(first_sequence=self.previous['last_sequence']+1,last_sequence=captured-1,frames=missing,reason='Closed capture tail is absent from finalized segment index; original partial files retained',recorded_epoch=time.time()))
                if self.events.run!=self.previous['generation']:
                    self.events.run=self.previous['generation'];self.events.event=lab.read(prior/'open-event.json')
                self.persist()
                self.events.finish(interrupted=True)
                atomic(prior/'analysis-summary.json',dict(self.previous,capture=health))
                atomic(prior/'analysis-complete.json',dict(stage='motion_analysis',last_sequence=self.previous['last_sequence'],analyzed_frames=self.previous.get('generation_analyzed_frames'),missing_frames=self.previous.get('generation_missing_frames'),integrity_ok=self.previous.get('generation_missing_frames',0)==0,completed_epoch=time.time()))
        self.events.update(timing,boxes,metrics,generation,model_id)
        state=dict(state,preservation='durable_spool',capture_error=None,event_state='open' if self.events.event else 'idle',event_session=self.events.event['session_id'] if self.events.event else None)
        self.previous=state;self.state={k:state[k] for k in ['event_state','event_session']}
        self.write_seconds+=time.perf_counter()-started
        if time.monotonic()-self.last_save>=1:self.persist()
    def work(self):
        try:
            while not self.stop.is_set():
                try:record=self.pending.get(timeout=.1)
                except queue.Empty:
                    if self.previous and time.monotonic()-self.last_save>=1:self.persist()
                    continue
                try:
                    if record[0]=='barrier':self.persist();record[1].set()
                    else:self.process(record)
                finally:self.pending.task_done()
        except Exception as exc:
            self.error=str(exc)
            fault=dict(self.committed,phase='journal_error',error=self.error,analyzed_epoch=self.committed.get('analyzed_epoch',0))
            try:atomic(self.folder/'native-analysis.json',fault)
            except OSError:pass
            print('Native evidence journal failed; restarting from durable checkpoint:',self.error,flush=True)
            self.stop.set()
