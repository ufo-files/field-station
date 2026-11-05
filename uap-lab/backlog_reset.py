"""Checkpoint catch-up; caller must stop recognition and hold its service lock."""
import json,os,sqlite3,sys,time
from pathlib import Path

def capture_health(folder):
 """A closed RF-only generation has no camera frames to discard."""
 try:return json.loads((folder/'capture-health.json').read_text())
 except FileNotFoundError:
  import re
  names={p.name for p in folder.iterdir()}
  if {'generation.json','closed.json'}<=names and all(n in {'generation.json','closed.json'} or re.fullmatch(r'rf-[0-9]+\.jsonl',n) for n in names):
   return dict(captured_frames=0,empty_camera_generation=True)
  raise

def reset(app,root,receipt):
 output=root/'uap-lab/recognition'
 os.environ.update(json.loads((app/'environment.json').read_text()));sys.path[:0]=[str(app/'uap-lab'),str(app/'uap-lab/recognition')]
 from native_frames import timing_rows
 from spool_events import SpoolEvents,atomic
 store=sqlite3.connect(output/'results.sqlite');state_raw,background=store.execute('select state,background from checkpoint where id=1').fetchone();state=json.loads(state_raw)
 generation=json.loads((root/'capture-spool/active.json').read_text())['generation'];folder=root/'capture-spool'/generation
 old_generation=state['generation']
 lines=(folder/'segments-index.jsonl').read_bytes().splitlines(keepends=True);lines=[x for x in lines if x.endswith(b'\n')];entry=json.loads(lines[-1]);timing=timing_rows(folder,entry['start'],entry['end']);import av
 with av.open(str(folder/entry['file'])) as container:
  frame=next(container.decode(video=0));first_pts=entry['start']+float(frame.pts*frame.time_base)
 first=min(timing,key=lambda r:abs(r['pts_seconds']-first_pts));assert abs(first['pts_seconds']-first_pts)<.003
 previous_sequence=(state['last_sequence'] if state['last_sequence'] is not None else state.get('intentionally_discarded_ranges',[{'last_sequence':-1}])[-1]['last_sequence']) if old_generation==generation else -1
 if old_generation==generation and first['sequence']<=previous_sequence:return dict(skipped='already_current')
 receipt.mkdir(parents=True,exist_ok=True)
 (receipt/'checkpoint-before.json').write_text(state_raw);(receipt/'background-before.bin').write_bytes(background or b'');native_path=root/'uap-lab/live/native-analysis.json';native=json.loads(native_path.read_text());(receipt/'native-analysis-before.json').write_text(json.dumps(native))
 skip=dict(generation=generation,first_sequence=previous_sequence+1,last_sequence=first['sequence']-1,frames=first['sequence']-previous_sequence-1,authorization='User explicitly requested clearing the analysis backlog while preserving all review clips and training labels.',epoch=time.time(),analyzed=False)
 prior_skips=[]
 if old_generation!=generation:
  old_created=json.loads((root/'capture-spool'/old_generation/'generation.json').read_text())['created_epoch']
  active_created=json.loads((folder/'generation.json').read_text())['created_epoch']
  for prior in (root/'capture-spool').glob('run-*'):
   try:
    created=json.loads((prior/'generation.json').read_text())['created_epoch']
    if not old_created<=created<active_created:continue
    health=capture_health(prior);start=(state.get('last_sequence') or 0)+1 if prior.name==old_generation else 0;end=health['captured_frames']-1
    if end>=start:prior_skips.append(dict(skip,generation=prior.name,first_sequence=start,last_sequence=end,frames=end-start+1))
    old_events=SpoolEvents(root/'capture-spool');old_events.run=prior.name;old_events.event=json.loads((prior/'open-event.json').read_text()) if (prior/'open-event.json').exists() else None
    if old_events.event:old_events.finish(interrupted=True,reason='user_authorized_backlog_reset')
   except FileNotFoundError:raise RuntimeError('Capture metadata missing; cannot audit generation skip')
 events=SpoolEvents(root/'capture-spool');events.run=generation;events.event=json.loads((folder/'open-event.json').read_text()) if (folder/'open-event.json').exists() else None
 if events.event:events.finish(interrupted=True,reason='user_authorized_backlog_reset')
 state.update(generation=generation,offset=sum(map(len,lines[:-1])),last_sequence=None,last_pts=None,tracks={},track_serial=0,background_shape=None,background_encoding='zlib',coverage_start_pts=entry['start'],coverage_first_sequence=None,intentionally_discarded_ranges=[*state.get('intentionally_discarded_ranges',[]),*prior_skips,skip])
 import zlib
 store.execute('update checkpoint set state=?, background=? where id=1',(json.dumps(state),zlib.compress(b'')));store.commit();store.close()
 native.update(generation=generation,last_sequence=first['sequence']-1,last_pts_seconds=first['pts_seconds']-.000001,coverage_start_sequence=first['sequence'],intentionally_discarded_ranges=[*native.get('intentionally_discarded_ranges',[]),*prior_skips,skip],phase='waiting_for_current_frame',error=None)
 atomic(native_path,native);events.acknowledge(generation,native)
 atomic(folder/'recognition-required.json',dict(start_pts=entry['start'],model=state['model'],intentionally_discarded_ranges=state['intentionally_discarded_ranges']))
 atomic(folder/'recognition-ack.json',dict(generation=generation,last_pts_seconds=first['pts_seconds']-.000001,last_sequence=first['sequence']-1,integrity_ok=True,coverage_start_pts=entry['start'],coverage_first_sequence=first['sequence'],intentionally_discarded_ranges=state['intentionally_discarded_ranges']))
 result=dict(discarded=dict(skip,frames=skip['frames']+sum(r['frames'] for r in prior_skips)),discarded_ranges=[*prior_skips,skip],new_start_sequence=first['sequence'],new_start_pts=first['pts_seconds'],preserved='All reviewed crops, saved video clips, annotations, training data, and existing analyzed results',receipt=str(receipt));atomic(receipt/'result.json',result);atomic(app/'maintenance/startup-discard/latest.json',result);return result
