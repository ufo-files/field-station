"""Durable local recognition suggestions. Never controls recording or discards evidence."""
import argparse,bisect,fcntl,hashlib,json,os,signal,sys,threading,time
from pathlib import Path
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import cv2
from stream_decode import StreamDecoder
from crop_client import CropClassifier
from native_tracks import NativeTracks
from recognition_store import AsyncRecognitionStore as RecognitionStore
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from native_motion import NativeMotion
from native_frames import timing_rows
from temporal_runtime import TemporalRuntime
from recognition_preview import RecognitionPreview
from classification_policy import eligible,apply_results

def read(path,default=None):
 try:return json.loads(path.read_text())
 except FileNotFoundError:return default

def atomic(path,value):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.replace(path)

def verify_source(source,expected):
 if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError('Native segment checksum mismatch')
 return True

def read_index(folder,offset):
 try:
  with (folder/'segments-index.jsonl').open('rb') as index:
   index.seek(offset);line=index.readline();next_offset=index.tell();upcoming=index.readline()
   return line,next_offset,upcoming
 except FileNotFoundError:
  if offset:raise # An existing journal disappearing is not normal startup.
  return b'',0,b'' # New capture generation can precede its first closed segment.

def run(config,output,stop,start_segment=None,stop_segment=None):
 output.mkdir(parents=True,exist_ok=True);root=Path(config['spool']);policy=read(Path(config['policy']));cv2.setNumThreads(int(config.get('motion_threads',2)))
 sink=None
 if config.get('event_owner') and stop_segment is None:
  from recognition_events import EventSink
  sink=EventSink(root)
 cv2.setNumThreads(int(config.get('motion_threads',2)))
 store=RecognitionStore(output/'results.sqlite');state,background=store.load();status=read(output/'status.json',{})
 if state and state['model']!=policy['version']:raise ValueError('Recognition model changed without a new checkpoint namespace')
 if state is None:
  generation=read(root/'active.json')['generation'];folder=root/generation;lines=(folder/'segments-index.jsonl').read_bytes().splitlines(keepends=True);complete=[line for line in lines if line.endswith(b'\n')];chosen=max(0,len(complete)-2) if start_segment is None else start_segment
  if chosen>=len(complete):raise ValueError('Requested initial segment unavailable')
  entry=json.loads(complete[chosen]);offset=sum(map(len,complete[:chosen]));state=dict(generation=generation,offset=offset,last_sequence=None,last_pts=None,frames=0,proposals=0,model=policy['version'],coverage_start_pts=entry['start'],coverage_first_sequence=None,tracks={},track_serial=0,source_timestamp_gaps=0)
  store.commit(state,None).result()
 preview=RecognitionPreview(output) if config.get('display_preview') else None
 temporal=TemporalRuntime(Path(config.get('active_model',str(output.parent/'active-model.json'))));temporal.refresh()
 detector=NativeMotion();detector.background=background;detector.last_pts=state['last_pts'];tracker=NativeTracks(state['generation']);tracker.tracks=state['tracks'];tracker.serial=state['track_serial'];tracker.last_sequence=state['last_sequence'];tracker.last_pts=state['last_pts']
 stages=dict(decode_wait=0.,motion_and_crops=0.,classification_wait=0.,checkpoint=0.,source_verification=0.)
 prefetched=None
 pending=deque();started=time.monotonic();run_frames=0;uncommitted=0;last_checkpoint=time.monotonic();folder=root/state['generation']
 pinned=None;required_generation=None
 def pin():
  nonlocal pinned,required_generation
  if stop_segment is not None:return
  if required_generation!=state['generation']:
   atomic(folder/'recognition-required.json',dict(start_pts=state['coverage_start_pts'],model=state['model'],intentionally_discarded_ranges=state.get('intentionally_discarded_ranges',[])));required_generation=state['generation']
  committed=store.last_committed
  if committed and committed.get('last_pts') is not None:
   identity=(committed['generation'],committed['last_sequence'])
   if identity!=pinned:
    atomic(root/committed['generation']/'recognition-ack.json',dict(generation=committed['generation'],last_pts_seconds=committed['last_pts'],last_sequence=committed['last_sequence'],integrity_ok=True,coverage_start_pts=committed['coverage_start_pts'],coverage_first_sequence=committed['coverage_first_sequence'],intentionally_discarded_ranges=committed.get('intentionally_discarded_ranges',[])));pinned=identity
 pin()
 def checkpoint():
  nonlocal uncommitted,last_checkpoint
  checkpoint_started=time.perf_counter()
  state.update(tracks=tracker.tracks,track_serial=tracker.serial)
  if sink:sink.flush()
  future=store.commit(state,detector.background);pin();uncommitted=0;last_checkpoint=time.monotonic();stages['checkpoint']+=time.perf_counter()-checkpoint_started
  return future
 def commit_one():
  nonlocal run_frames
  row,future=pending.popleft();wait_started=time.perf_counter();results=future.result();stages['classification_wait']+=time.perf_counter()-wait_started
  if any('error' in result for result in results):raise ValueError('Object classification failed; source retained for retry')
  indices=row.pop('classification_indices');apply_results(row['observations'],indices,results,policy)
  if preview is not None and row.get('preview_bgr') is not None:preview.submit(row.pop('preview_bgr'),row['observations'],row,state['generation'],state['model'])
  store.add(state['generation'],row,state['model']);state['frames']+=1;state['proposals']+=len(row['observations']);state['frames_with_proposals']=state.get('frames_with_proposals',0)+bool(row['observations']);state['appearance_inferences']=state.get('appearance_inferences',0)+len(results);state['below_minimum_size']=state.get('below_minimum_size',0)+len(row['observations'])-len(results);run_frames+=1
  status.update(last_sequence=row['sequence'],last_pts_seconds=row['pts_seconds'],frame_epoch=row['received_epoch'],latency_seconds=time.time()-row['received_epoch'],objects=row['observations'])
 try:
  with CropClassifier(config['worker'],config['model'],policy['version']) as classifier,StreamDecoder() as decoder,ThreadPoolExecutor(max_workers=1) as executor,ThreadPoolExecutor(max_workers=1) as verifier:
   while not stop.is_set():
    folder=root/state['generation']
    line,next_offset,upcoming=read_index(folder,state['offset'])
    if not line or not line.endswith(b'\n'):
     pin()
     if uncommitted and time.monotonic()-last_checkpoint>=config.get('checkpoint_seconds',60):checkpoint()
     if (folder/'closed.json').exists():
      created=read(folder/'generation.json')['created_epoch'];later=sorted((read(p/'generation.json')['created_epoch'],p.name) for p in root.glob('run-*') if (p/'generation.json').exists() and read(p/'generation.json')['created_epoch']>created)
      if later:
       checkpoint().result();pin() # Acknowledge the closed generation before replacing its cursor.
       state.update(generation=later[0][1],offset=0,last_sequence=None,last_pts=None,coverage_start_pts=0,coverage_first_sequence=None,tracks={},track_serial=0);detector=NativeMotion();tracker=NativeTracks(state['generation']);folder=root/state['generation'];checkpoint();continue
     stop.wait(.05);continue
    temporal.refresh();entry=json.loads(line);segment=int(Path(entry['file']).stem.split('-')[-1])
    if stop_segment is not None and segment>=stop_segment:break
    source_started=time.perf_counter();source=folder/entry['file']
    if source.is_symlink() or source.parent!=folder or not source.is_file():raise ValueError('Missing or unsafe native segment')
    if prefetched and prefetched[0]==str(source) and prefetched[1]==entry['sha256']:prefetched[2].result()
    else:verify_source(source,entry['sha256'])
    prefetched=None
    if upcoming.endswith(b'\n'):
     next_entry=json.loads(upcoming);next_source=folder/next_entry['file']
     if next_source.parent!=folder or next_source.is_symlink():raise ValueError('Unsafe prefetched segment')
     prefetched=(str(next_source),next_entry['sha256'],verifier.submit(verify_source,next_source,next_entry['sha256']))
    timings=timing_rows(folder,entry['start'],entry['end']);pts_values=[t['pts_seconds'] for t in timings];health=read(folder/'capture-health.json',{});stages['source_verification']+=time.perf_counter()-source_started;previous_finish=time.perf_counter()
    display_current=preview is not None and time.time()-entry.get('end_epoch',0)<3
    for image,header in decoder.frames(source,preview_interval=.2 if display_current else 0):
     frame_started=time.perf_counter();stages['decode_wait']+=frame_started-previous_finish
     pts=entry['start']+header['pts_seconds'];near=bisect.bisect_left(pts_values,pts);options=[i for i in (near-1,near) if 0<=i<len(timings)]
     choice=min(options,key=lambda i:abs(pts_values[i]-pts)) if options else None
     if choice is None or abs(pts_values[choice]-pts)>.003:raise ValueError('Decoded frame lacks original PTS')
     timing=timings[choice];seq=timing['sequence'];pts=timing['pts_seconds']
     if state['last_sequence'] is not None and seq!=state['last_sequence']+1:raise ValueError('Native sequence gap, repeat or reversal')
     if state['last_pts'] is not None:
      delta=pts-state['last_pts']
      if delta<=0:raise ValueError('Nonmonotonic native timestamp')
      state['source_timestamp_gaps']+=int(delta>1.5/59.94005994)
     if state['coverage_first_sequence'] is None:state['coverage_first_sequence']=seq
     boxes,metrics=detector.update(image,pts)
     if sink:sink.submit(timing,boxes,metrics,state['generation'],health,state)
     observations=tracker.update(seq,pts,boxes);encoded=[];indices=[]
     for observation_index,observation in enumerate(observations):
      x,y,w,h=observation['box'];crop=image[y:y+h,x:x+w]
      from temporal_model import shape_descriptor
      observation['shape_descriptor']=shape_descriptor(crop)
      if not eligible(observation,policy):continue
      ok,data=cv2.imencode('.png',crop)
      if not ok:raise ValueError('Native crop encoding failed')
      encoded.append(data.tobytes());indices.append(observation_index)
     temporal.observe_many(observations,tracker.tracks,pts,image.shape[1],image.shape[0])
     row=dict(timing,observations=observations,classification_indices=indices)
     if header.get('preview_bgr') is not None:row['preview_bgr']=header['preview_bgr']
     pending.append((row,executor.submit(classifier.predict,encoded,str(seq))))
     stages['motion_and_crops']+=time.perf_counter()-frame_started
     if len(pending)>=4:commit_one()
     state.update(last_sequence=seq,last_pts=pts);previous_finish=time.perf_counter()
    while pending:commit_one()
    state['offset']=next_offset;uncommitted+=1
    if uncommitted>=config.get('checkpoint_segments',60) or time.monotonic()-last_checkpoint>=config.get('checkpoint_seconds',60):checkpoint()
    pin();health=read(folder/'capture-health.json',{});status.update(phase='shadow_analysis',updated_epoch=time.time(),model=state['model'],generation=state['generation'],analyzed_frames=state['frames'],classified_proposals=state['proposals']-state.get('below_minimum_size',0),processed_proposals=state['proposals'],below_minimum_size_observations=state.get('below_minimum_size',0),appearance_inferences_since_optimization=state.get('appearance_inferences',0),classification_policy='retain_all_observations_infer_only_existing_size_eligible',pipeline_version='latency-policy-vectorized-v2',intentionally_discarded_ranges=state.get('intentionally_discarded_ranges',[]),coverage_first_sequence=state['coverage_first_sequence'],coverage_start_pts=state['coverage_start_pts'],missing_frames=0,classification_errors=0,source_timestamp_gaps=state['source_timestamp_gaps'],backlog_frames=max(0,health.get('captured_frames',seq+1)-seq-1),run_throughput_fps=run_frames/max(.001,time.monotonic()-started),classification_queue_capacity=4,uncommitted_segments=uncommitted,capture_control=False,error=None,integrity_ok=True,stage_seconds=dict(stages),run_frames=run_frames,motion_threads=cv2.getNumThreads(),writer_queue_records=store.pending.qsize(),durable_sequence=(store.last_committed or {}).get('last_sequence'),checkpoint_write_seconds=store.commit_seconds,temporal=temporal.status(),display_preview=preview.status() if preview else None)
    atomic(output/'status.json',status)
   while pending:commit_one()
   checkpoint()
 except BaseException as exc:
  status.update(phase='error',error=str(exc),updated_epoch=time.time(),failures=status.get('failures',0)+1,integrity_ok=False);atomic(output/'status.json',status);raise
 finally:
  store.close();pin()
  if sink:sink.close()
  if preview:preview.close()

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--start-segment',type=int);parser.add_argument('--stop-segment',type=int);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
 stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
 with (args.output/'service.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);run(read(args.config),args.output,stop,args.start_segment,args.stop_segment)
