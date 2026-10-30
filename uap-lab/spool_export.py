"""Reconstruct provisional sessions from durable video and RF, including delayed analysis."""
import json,os,shutil,threading,time,math
from pathlib import Path
from datetime import datetime,timezone
import lab
from spool_events import atomic

def export_event(root,path):
    event=json.loads(path.read_text())
    if event.get('state')=='exported':return
    folder=lab.STATION/'sessions'/event['session_id']
    if (folder/'manifest.json').exists():
        event.update(state='exported',exported_epoch=time.time());atomic(path,event);return
    generation=root/event['generation'];entries=[json.loads(line) for line in (generation/'segments-index.jsonl').read_text().splitlines()]
    relevant=[s for s in entries if s['end']>event['start_pts'] and s['start']<event['end_pts']]
    if not relevant:return
    closed=(generation/'closed.json').exists()
    if relevant[-1]['end']<event['end_pts'] and not closed:return
    folder=lab.STATION/'sessions'/event['session_id'];folder.mkdir(exist_ok=True);segments_dir=folder/'buffer-segments';segments_dir.mkdir(exist_ok=True)
    start=max(event['start_pts'],relevant[0]['start']);end=min(event['end_pts'],relevant[-1]['end'])
    anchor=event['frame_epoch']-event['onset_pts'];segments=[]
    for original in relevant:
        segment=dict(original,start_epoch=anchor+original['start'],end_epoch=anchor+original['end']);source=generation/segment['file'];dest=segments_dir/segment['file']
        if not dest.exists():
            try:os.link(source,dest)
            except OSError:shutil.copy2(source,dest)
        segments.append(segment)
        for bucket in range(max(0,math.floor(segment['start'])-1),math.ceil(segment['end'])+1):
            source=generation/f'frame-times-{bucket:09d}.jsonl'
            if source.exists():shutil.copy2(source,segments_dir/source.name)
    native_journal=generation/'candidates'/(event['session_id']+'.jsonl')
    if native_journal.exists():shutil.copy2(native_journal,folder/'provisional-candidates.jsonl')
    rf=[]
    rf_sources=[generation/'rf.jsonl',*[generation/f'rf-{bucket:012d}.jsonl' for bucket in range(int((anchor+start)//60),int((anchor+end)//60)+1)]]
    for rf_source in rf_sources:
        if not rf_source.exists():continue
        for line in rf_source.read_text().splitlines():
            try:row=json.loads(line)
            except ValueError:continue
            epoch=row.get('captured_epoch',0)
            if anchor+start<=epoch<=anchor+end:rf.append(dict(captured_at=datetime.fromtimestamp(epoch,timezone.utc).isoformat(),elapsed_seconds=epoch-anchor-start,spectrum=row['spectrum']))
    rfpath=folder/'rf.jsonl';tmp=rfpath.with_suffix('.tmp');tmp.write_text(''.join(json.dumps(r)+'\n' for r in rf));tmp.replace(rfpath)
    atomic(folder/'buffer-state.json',dict(state='queued',folder=str(folder),requested_start_epoch=anchor+start,requested_end_epoch=anchor+end,requested_prebuffer_start_epoch=anchor+event['start_pts'],segments=segments,tail_complete=end>=event['end_pts']))
    manifest=dict(id=event['session_id'],title='Provisional motion',state='completed',created=event['created'],started_epoch=anchor+start,started_at=datetime.fromtimestamp(anchor+start,timezone.utc).isoformat(),stopped_epoch=anchor+end,elapsed_seconds=end-start,buffered_capture=True,provisional=True,capture_origin='provisional_motion',classification_state='pending',video_archive='video.mkv',video_playback=dict(state='queued',file='video.mp4'),frame_export_mode='selected',frame_fps=60,video_fps=60,frames=dict(state='queued',mode='selected',fps=60,count=0),pre_roll_seconds=10,pre_roll_actual_seconds=event['onset_pts']-start,pre_roll_complete=event['onset_pts']-start>=9.99,post_roll_seconds=10,post_roll_actual_seconds=max(0,end-event.get('last_seen_pts',event['onset_pts'])),post_roll_complete=end-event.get('last_seen_pts',event['onset_pts'])>=9.99,capture_interrupted=event.get('interrupted',False),window_limited=event.get('finish_reason')=='window_limit' or event['end_pts']-event['start_pts']>=59.99,buffer_tail_complete=end>=event['end_pts'],rf_records=len(rf),spool_generation=event['generation'],timing='Original capture PTS retained; UTC is host receipt time, not calibrated exposure time.',files={})
    atomic(folder/'provisional.json',dict(schema_version=2,session_id=event['session_id'],created=event['created'],state='captured',classification='unclassified',model_id=event.get('model_id'),automatic_deletion=False))
    # Publish completion last so other workers never observe a half-copied session.
    if not (folder/'manifest.json').exists():atomic(folder/'manifest.json',manifest)
    event.update(state='exported',exported_epoch=time.time());atomic(path,event)

def watch(root):
    root=Path(root)
    while True:
        try:
            for path in root.glob('run-*/events/*.json'):export_event(root,path)
        except Exception as exc:print('Spool event export:',str(exc),flush=True)
        time.sleep(2)
