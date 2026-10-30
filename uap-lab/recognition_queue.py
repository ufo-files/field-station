"""Reuse durable native recognition without accepting suggestions as reviewed labels."""
import json,sqlite3
from contextlib import closing
from collections import Counter

def local_summary(meta):
    import lab
    from recognition_review import mapping
    db=lab.DATA/'recognition/results.sqlite'
    status=lab.read(lab.DATA/'recognition/status.json',{})
    sid=meta.get('provenance',{}).get('session_id')
    if not sid or not db.exists():return None
    session=lab.STATION/'sessions'/sid
    manifest=lab.read(session/'manifest.json',{});buffer=lab.read(session/'buffer-state.json',{})
    generation=manifest.get('spool_generation');segments=buffer.get('segments',[])
    if not generation or not segments:return None
    # Skip old recordings outside the candidate's known coverage without decoding
    # them repeatedly. Existing reference jobs retain their own provenance.
    if generation==status.get('generation') and segments[-1]['end']<status.get('coverage_start_pts',0):return None
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=5)) as conn:
        first=conn.execute('SELECT pts FROM frames WHERE generation=? ORDER BY pts LIMIT 1',(generation,)).fetchone()
        last=conn.execute('SELECT pts FROM frames WHERE generation=? ORDER BY pts DESC LIMIT 1',(generation,)).fetchone()
        if first is None:return None
        bounds=(first[0],last[0])
        if segments[-1]['end']<bounds[0]:return None
        if segments[0]['start']<bounds[0]:return None
        # This returns a pending state, never permission for a duplicate M6 run.
        if bounds[1]<segments[-1]['end']-0.05:return dict(state='waiting_local_analysis',classification='unclassified',automatic_deletion=False)
    origin=mapping(lab.video_path(meta['id']),meta);frames=origin['frames']
    if not frames:raise ValueError('Empty native recognition mapping')
    expected=[r['sequence'] for r in frames];labels=Counter();models=set();observed=[];proposals=0
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=5)) as conn:
        rows=conn.execute('SELECT sequence,model,observations FROM frames WHERE generation=? AND sequence>=? AND sequence<=? ORDER BY sequence',(generation,expected[0],expected[-1]))
        for sequence,model,encoded in rows:
            observed.append(sequence);models.add(model)
            for observation in json.loads(encoded):
                labels[observation['suggested_label']]+=1;proposals+=1
    if observed!=expected:return dict(state='waiting_local_analysis',classification='unclassified',processed_frames=len(observed),frame_count=len(expected),automatic_deletion=False)
    if len(models)!=1:raise ValueError('Mixed recognition model versions require separate review')
    return dict(state='review_required',classification='local_model_suggestions',processed_frames=len(expected),frame_count=len(expected),candidate_model_id=next(iter(models)),suggested_objects=proposals,suggested_label_counts=dict(labels),recognition_generation=origin['generation'],recognition_first_sequence=expected[0],recognition_last_sequence=expected[-1],human_confirmed=False,automatic_deletion=False,message='Every native frame analyzed locally. Confirm or correct suggestions in labeling; no automatic negative disposal.')
