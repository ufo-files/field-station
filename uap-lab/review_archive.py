"""Only completed human review can promote provisional evidence to public archive."""
import re
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
    event=read(Path(data).parent/'notifications/outbox'/key/'event.json')
    if not event.get('generation'):return
    for decision_path in (Path(data).parent/'sessions').glob('*/archive-decision.json'):
        path=decision_path.parent/'manifest.json'
        manifest=read(path)
        if manifest.get('spool_generation')!=event.get('generation'):continue
        segments=read(path.parent/'buffer-state.json').get('segments',[])
        if segments and segments[0]['start']<=event.get('pts_seconds',-1)<segments[-1]['end']:
            target=path.parent/'archive-decision.json'
            if target.exists():
                decision=read(target);decision.update(bundle_ready=False,review_required=True)
                temporary=target.with_suffix('.tmp-'+uuid.uuid4().hex)
                temporary.write_text(json.dumps(decision));temporary.replace(target)
