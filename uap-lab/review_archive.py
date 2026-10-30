"""Only completed human review can promote provisional evidence to public archive."""
import re
from collections import Counter

def record_decision(folder,meta,review):
    import lab
    sid=meta.get('provenance',{}).get('session_id')
    if not sid or not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid) or not review.get('completed'):return None
    labels=Counter(a['label'] for a in lab.read(folder/'annotations.json',[]))
    decision=dict(schema=1,session_id=sid,video_id=meta['id'],source_sha256=meta['sha256'],human_confirmed=True,reviewed_epoch=review['reviewed_at'],confirmed_anomalous=bool(labels.get('anomalous')),labels=dict(labels),no_target=review.get('no_target',False))
    outbox=lab.DATA/'archive-decisions';outbox.mkdir(exist_ok=True);lab.save(outbox/(sid+'.json'),decision)
    return decision

def sync_decisions():
    import lab
    outbox=lab.DATA/'archive-decisions'
    if not outbox.exists():return
    for path in outbox.glob('*.json'):
        if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',path.stem):continue
        decision=lab.read(path,{});folder=lab.STATION/'sessions'/path.stem
        if not (folder/'manifest.json').is_file():continue
        dest=folder/'archive-decision.json'
        if lab.read(dest)!=decision:lab.save(dest,decision)
