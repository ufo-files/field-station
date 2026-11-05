"""Only completed human review can promote provisional evidence to public archive."""
import re,sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]/'shared'))
from collections import Counter

def record_decision(folder,meta,review):
    import lab
    sid=meta.get('provenance',{}).get('session_id')
    if not sid or not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid) or not review.get('completed') or review.get('automated_event'):return None
    invalidate_session(sid)
    labels=Counter(a['label'] for a in lab.read(folder/'annotations.json',[]))
    decision=dict(schema=1,session_id=sid,video_id=meta['id'],source_sha256=meta['sha256'],human_confirmed=True,reviewed_epoch=review['reviewed_at'],confirmed_anomalous=bool(labels.get('anomalous')),labels=dict(labels),no_target=review.get('no_target',False))
    outbox=lab.DATA/'archive-decisions';outbox.mkdir(exist_ok=True);lab.save(outbox/(sid+'.json'),decision)
    return decision

def sync_decisions():
    from archive_exports import reconcile
    reconcile()

def invalidate_session(sid):
    import lab,os
    from pathlib import Path
    if not SID_VALID(sid):return
    folder=Path(os.environ.get('CAPTURE_DATA',str(lab.STATION/'sessions')))/sid
    path=folder/'archive-decision.json'
    if path.exists():
        decision=lab.read(path,{})
        decision.update(bundle_ready=False,review_required=True)
        lab.save(path,decision)

def SID_VALID(sid):return isinstance(sid,str) and re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid)

def invalidate_event(data,key):
    import json,uuid
    from pathlib import Path
    def read(path):
        try:return json.loads(path.read_text())
        except (OSError,ValueError):return {}
    from email_training import batch_metadata_cache
    cache=batch_metadata_cache(data)
    event=read(Path(data).parent/'notifications/outbox'/key/'event.json')
    if not event.get('generation'):return
    # Read existing manifests directly. Probing a usually absent decision file
    # in every recording directory can stall APFS metadata I/O for minutes.
    sessions=Path(data).parent/'sessions'
    from session_catalog import lookup
    names=lookup(Path(data).parent,event['generation'])
    if names is None:
        try:names=list(sessions.iterdir())
        except FileNotFoundError:return
    for folder in names:
        if not SID_VALID(folder.name):continue
        path=folder/'manifest.json'
        manifest=cache[path] if cache is not None and path in cache else read(path)
        closed=manifest.get('state') in ('completed','interrupted')
        if cache is not None and closed:cache[path]=manifest
        if manifest.get('spool_generation')!=event.get('generation'):continue
        buffer=path.parent/'buffer-state.json'
        state=cache[buffer] if cache is not None and buffer in cache else read(buffer)
        if cache is not None and closed:cache[buffer]=state
        segments=state.get('segments',[])
        if segments and segments[0]['start']<=event.get('pts_seconds',-1)<segments[-1]['end']:
            target=path.parent/'archive-decision.json'
            if target.exists():
                decision=read(target);decision.update(bundle_ready=False,review_required=True)
                temporary=target.with_suffix('.tmp-'+uuid.uuid4().hex)
                temporary.write_text(json.dumps(decision));temporary.replace(target)
