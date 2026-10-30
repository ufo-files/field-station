"""Explicit track corrections preserve reviewed labels, images and SHA review history."""
import hashlib,json,time,uuid

def link(vid,annotation_ids):
    import lab
    folder=lab.video_path(vid)
    if not isinstance(annotation_ids,list) or not 2<=len(annotation_ids)<=200 or len(set(annotation_ids))!=len(annotation_ids):raise ValueError('Choose 2–200 distinct observations of the same object')
    ids={lab.checked_id(value) for value in annotation_ids}
    with lab._per_video_lock(lab._REVIEW_LOCKS,folder):
        meta=lab.read(folder/'video.json')
        if not meta:raise ValueError('Video not found')
        rows=lab.read(folder/'annotations.json',[]);selected=[r for r in rows if r['id'] in ids]
        if len(selected)!=len(ids):raise ValueError('An observation is missing; reload the video')
        if len({r['label'] for r in selected})!=1:raise ValueError('One object track must have one label')
        times=[r['time'] for r in selected]
        if len(set(times))!=len(times):raise ValueError('Different objects in the same frame cannot share a track')
        native=[r['frame_index'] for r in selected if r.get('frame_index') is not None]
        if len(set(native))!=len(native):raise ValueError('A track can contain only one observation per native frame')
        track=uuid.uuid4().hex;history=folder/'track-history';history.mkdir(exist_ok=True)
        audit=dict(schema=1,created_epoch=time.time(),video_id=vid,source_sha256=meta.get('sha256'),annotation_ids=sorted(ids),track_id=track,association='explicit_user_confirmation',before=rows)
        lab.save(history/(str(time.time_ns())+'-'+track+'.json'),audit)
        updated=[dict(r,track_id=track,track_association='explicit_user_confirmation') if r['id'] in ids else r for r in rows]
        lab.save(folder/'annotations.json',updated)
        return dict(track_id=track,observations=len(selected),annotations=updated,review_history_preserved=True)
