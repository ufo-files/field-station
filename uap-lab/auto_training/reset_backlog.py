"""Checkpoint catch-up; caller must stop recognition and hold its service lock."""
import json,os,sqlite3,sys,time
from pathlib import Path

def reset(app,root,receipt):
 output=root/'uap-lab/recognition'
 os.environ.update(json.loads((app/'environment.json').read_text()));sys.path[:0]=[str(app/'uap-lab'),str(app/'uap-lab/recognition')]
 from native_frames import timing_rows
 from spool_events import SpoolEvents,atomic
 store=sqlite3.connect(output/'results.sqlite');state_raw,background=store.execute('select state,background from checkpoint where id=1').fetchone();state=json.loads(state_raw)
 generation=json.loads((root/'capture-spool/active.json').read_text())['generation'];folder=root/'capture-spool'/generation
 if generation!=state['generation']:return dict(skipped='generation_transition')
 lines=(folder/'segments-index.jsonl').read_bytes().splitlines(keepends=True);lines=[x for x in lines if x.endswith(b'\n')];entry=json.loads(lines[-1]);timing=timing_rows(folder,entry['start'],entry['end']);import av
 with av.open(str(folder/entry['file'])) as container:
  frame=next(container.decode(video=0));first_pts=entry['start']+float(frame.pts*frame.time_base)
 first=min(timing,key=lambda r:abs(r['pts_seconds']-first_pts));assert abs(first['pts_seconds']-first_pts)<.003
 previous_sequence=state['last_sequence'] if state['last_sequence'] is not None else state['intentionally_discarded_ranges'][-1]['last_sequence']
 if first['sequence']<=previous_sequence:return dict(skipped='already_current')
 receipt.mkdir(parents=True,exist_ok=True)
 (receipt/'checkpoint-before.json').write_text(state_raw);(receipt/'background-before.bin').write_bytes(background or b'');native_path=root/'uap-lab/live/native-analysis.json';native=json.loads(native_path.read_text());(receipt/'native-analysis-before.json').write_text(json.dumps(native))
 skip=dict(generation=generation,first_sequence=previous_sequence+1,last_sequence=first['sequence']-1,frames=first['sequence']-previous_sequence-1,authorization='User explicitly requested clearing the analysis backlog while preserving all review clips and training labels.',epoch=time.time(),analyzed=False)
 events=SpoolEvents(root/'capture-spool');events.run=generation;events.event=json.loads((folder/'open-event.json').read_text()) if (folder/'open-event.json').exists() else None
 if events.event:events.finish(interrupted=True,reason='user_authorized_backlog_reset')
 state.update(offset=sum(map(len,lines[:-1])),last_sequence=None,last_pts=None,tracks={},track_serial=0,background_shape=None,background_encoding='zlib',coverage_start_pts=entry['start'],coverage_first_sequence=None,intentionally_discarded_ranges=[*state.get('intentionally_discarded_ranges',[]),skip])
 import zlib
 store.execute('update checkpoint set state=?, background=? where id=1',(json.dumps(state),zlib.compress(b'')));store.commit();store.close()
 native.update(last_sequence=first['sequence']-1,last_pts_seconds=first['pts_seconds']-.000001,coverage_start_sequence=first['sequence'],intentionally_discarded_ranges=[*native.get('intentionally_discarded_ranges',[]),skip],phase='waiting_for_current_frame',error=None)
 atomic(native_path,native);events.acknowledge(generation,native)
 atomic(folder/'recognition-required.json',dict(start_pts=entry['start'],model=state['model'],intentionally_discarded_ranges=state['intentionally_discarded_ranges']))
 atomic(folder/'recognition-ack.json',dict(generation=generation,last_pts_seconds=first['pts_seconds']-.000001,last_sequence=first['sequence']-1,integrity_ok=True,coverage_start_pts=entry['start'],coverage_first_sequence=first['sequence'],intentionally_discarded_ranges=state['intentionally_discarded_ranges']))
 result=dict(discarded=skip,new_start_sequence=first['sequence'],new_start_pts=first['pts_seconds'],preserved='All reviewed crops, saved video clips, annotations, training data, and existing analyzed results',receipt=str(receipt));atomic(receipt/'result.json',result);atomic(app/'maintenance/startup-discard/latest.json',result);return result
