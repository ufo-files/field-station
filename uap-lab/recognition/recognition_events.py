"""Transfer event ownership without gaps or replaying already-committed triggers."""
import threading,time
class EventSink:
 def __init__(self,root):
  import lab
  from live_monitor import LiveMonitor
  from native_journal import NativeJournal
  self.lab=lab;self.monitor=LiveMonitor(start_workers=False);self.monitor.stop_event=threading.Event();self.previous=lab.read(self.monitor.folder/'native-analysis.json',{});self.root=root;self.started=time.monotonic();self.frames=0;self.config_checked=0;self.model=None
  self.journal=NativeJournal(root,self.monitor.folder,self.monitor,lambda _:None);self.journal.start()
 def submit(self,timing,boxes,metrics,generation,health,recognition):
  previous=self.previous;sequence=timing['sequence'];same=previous.get('generation')==generation
  if same and sequence<=previous.get('last_sequence',-1):return
  expected=previous.get('last_sequence',-1)+1 if same else 0
  if sequence!=expected:raise ValueError('Event ownership would skip native frames')
  self.frames+=1
  state=dict(previous);count=previous.get('generation_analyzed_frames',0)+1 if same else 1
  state.update(phase='analyzing',analysis_kind='native_frame_motion_and_shadow_recognition',generation=generation,last_sequence=sequence,last_pts_seconds=timing['pts_seconds'],analyzed_epoch=time.time(),analyzed_frames=previous.get('analyzed_frames',0)+1,generation_analyzed_frames=count,generation_missing_frames=previous.get('generation_missing_frames',0) if same else 0,capture=health,latency_seconds=time.time()-timing['received_epoch'],backlog_frames=max(0,health.get('captured_frames',sequence+1)-sequence-1),candidate_count=len(boxes),analyzed_fps=self.frames/max(.001,time.monotonic()-self.started),error=None,recognition_examined_frames=recognition['frames'],model_classified_frames=recognition.get('frames_with_proposals',0),model_classified_proposals=recognition['proposals']-recognition.get('below_minimum_size',0),processed_proposals=recognition['proposals'],below_minimum_size_observations=recognition.get('below_minimum_size',0),classification_role='suggestions_only',capture_control='motion_provisional',preservation='durable_spool')
  state['max_latency_seconds']=max(state.get('max_latency_seconds',0),state['latency_seconds']);
  if time.monotonic()-self.config_checked>=5:
   self.monitor.config=self.lab.read(self.monitor.folder/'config.json',self.monitor.config);self.model=(self.lab.read(self.lab.DATA/'active-model.json') or {}).get('id');self.config_checked=time.monotonic()
  model=self.model;enabled=self.monitor.config.get('provisional_enabled',True)
  self.journal.submit((timing,boxes if enabled else [],metrics if enabled else {},generation,model,state));self.previous=state
 def flush(self):self.journal.flush()
 def close(self):self.monitor.stop_event.set()
