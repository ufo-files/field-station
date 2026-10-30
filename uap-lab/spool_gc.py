"""Age- and acknowledgment-gated spool retention. Session evidence is never removed."""
import json,time,os,re
from pathlib import Path
from spool_events import atomic

def cleanup(root,now=None,retention_seconds=86400):
    root=Path(root);now=time.time() if now is None else now;deleted=retained=freed=0
    for run in root.glob('run-*'):
        ack_path=run/'analysis-ack.json'
        if not ack_path.exists():continue
        ack=json.loads(ack_path.read_text())
        if ack.get('generation')!=run.name or not ack.get('integrity_ok',False):continue
        recognition_required=run/'recognition-required.json'
        recognition_limit=None;recognition_start=None
        if recognition_required.exists():
            required=json.loads(recognition_required.read_text());recognition_start=required['start_pts']
            semantic=run/'recognition-ack.json'
            if semantic.exists():
                completed=json.loads(semantic.read_text())
                if completed.get('generation')==run.name and completed.get('integrity_ok'):recognition_limit=completed['last_pts_seconds']-30
        pending=[]
        for path in [run/'open-event.json',*run.glob('events/*.json')]:
            if not path.exists():continue
            event=json.loads(path.read_text())
            if event.get('state')!='exported':pending.append((event['start_pts'],event['end_pts']))
        state_path=run/'retention-cursor.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else dict(offset=0,timing_bucket=0)
        index=run/'segments-index.jsonl'
        def entries():
            if index.exists():
                with index.open() as source:
                    source.seek(state['offset'])
                    while True:
                        line=source.readline()
                        if not line or not line.endswith('\n'):break
                        yield json.loads(line),source.tell()
            else:
                for metadata in sorted(run.glob('segment-*.mkv.json')):yield json.loads(metadata.read_text()),0
        last_deleted_end=None
        for segment,offset in entries():
            eligible=segment['end_epoch']<now-retention_seconds and segment['end']<ack['last_pts_seconds']-30 and not any(segment['start']<end and segment['end']>start for start,end in pending)
            if recognition_start is not None and segment['end']>=recognition_start-30:
                eligible=eligible and recognition_limit is not None and segment['end']<recognition_limit
            if not eligible:
                retained+=1
                # Ordered index: retain all later entries rather than rescan a day of files.
                break
            name=segment['file']
            if not re.fullmatch(r'segment-\d+\.mkv',name):raise ValueError('Unsafe spool filename')
            source=run/name
            if source.is_symlink():raise ValueError('Unsafe spool source')
            if source.exists():
                size=source.stat().st_size
                with (root/'retention-journal.jsonl').open('a') as log:
                    log.write(json.dumps(dict(epoch=now,generation=run.name,file=name,sha256=segment.get('sha256'),reason='expired_acknowledged_unpinned'))+'\n');log.flush();os.fsync(log.fileno())
                source.unlink();freed+=size;deleted+=1
            (run/(name+'.json')).unlink(missing_ok=True)
            state['offset']=offset;last_deleted_end=segment['end']
        if last_deleted_end is not None:
            # Keep neighboring timestamp buckets needed for Matroska rounding.
            stop=max(0,int(last_deleted_end)-2)
            for bucket in range(state.get('timing_bucket',0),stop):(run/f'frame-times-{bucket:09d}.jsonl').unlink(missing_ok=True)
            state['timing_bucket']=stop
            for path in run.glob('rf-*.jsonl'):
                try:end_epoch=(int(path.stem.split('-')[-1])+1)*60
                except ValueError:continue
                if end_epoch<now-retention_seconds and not pending:path.unlink()
            atomic(state_path,state)
    atomic(root/'retention-status.json',dict(epoch=now,retention_seconds=retention_seconds,deleted_segments=deleted,blocked_generations=retained,unlinked_bytes=freed))
    return deleted

def watch(root,stop):
    while not stop.wait(60):
        try:cleanup(root)
        except Exception as exc:print('Spool retention:',str(exc),flush=True)
