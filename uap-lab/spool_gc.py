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
        # Sent or queued alert clips must remain reproducible until copied into their outbox.
        for event_path in (root.parent/'notifications/outbox').glob('*/event.json'):
            event=json.loads(event_path.read_text())
            if event.get('test') or event.get('generation')!=run.name:continue
            delivery_path=event_path.parent/'delivery.json'
            delivery=json.loads(delivery_path.read_text()) if delivery_path.exists() else {}
            if delivery.get('state') in ('cancelled','suppressed','expired'):continue
            from alert_evidence import backed_up
            if not (event_path.parent/'review-clip.json').exists() and not backed_up(root.parent,event,event_path.parent):pending.append((event['pts_seconds']-5,event['pts_seconds']+5))
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
        last_deleted_end=None;batch=[]
        def flush_batch():
            nonlocal deleted,freed,last_deleted_end
            if not batch:return
            # Durably journal the complete batch BEFORE removing any media.
            with (root/'retention-journal.jsonl').open('a') as log:
                for segment,offset in batch:log.write(json.dumps(dict(epoch=now,generation=run.name,file=segment['file'],sha256=segment.get('sha256'),reason='expired_acknowledged_unpinned'))+'\n')
                log.flush();os.fsync(log.fileno())
            for segment,offset in batch:
                source=run/segment['file']
                if source.is_symlink():raise ValueError('Unsafe spool source')
                if source.exists():
                    size=source.stat().st_size;source.unlink();freed+=size;deleted+=1
                (run/(segment['file']+'.json')).unlink(missing_ok=True)
                state['offset']=offset;last_deleted_end=segment['end']
            atomic(state_path,state)
            atomic(root/'retention-status.json',dict(epoch=now,phase='cleaning',retention_seconds=retention_seconds,deleted_segments=deleted,unlinked_bytes=freed))
            batch.clear()
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
            batch.append((segment,offset))
            if len(batch)>=256:flush_batch()
        flush_batch()
        if last_deleted_end is not None:
            # Keep neighboring timestamp buckets needed for Matroska rounding.
            stop=max(0,int(last_deleted_end)-2)
            # Timing records remain available for recognition provenance after raw expiry.
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
        try:
            policy=Path(root).parent/'retention-policy.json'
            seconds=json.loads(policy.read_text()).get('spool_retention_seconds',86400) if policy.exists() else 86400
            if not isinstance(seconds,(int,float)) or not 600<=seconds<=86400:raise ValueError('Invalid spool retention interval')
            cleanup(root,retention_seconds=seconds)
        except Exception as exc:print('Spool retention:',str(exc),flush=True)
