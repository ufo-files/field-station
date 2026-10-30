"""Browse current annotations; audit removals and invalidate stale review decisions."""
import time, re, uuid

def listing(label='',search='',offset=0,limit=48):
    import lab
    offset=max(0,int(offset));limit=max(1,min(96,int(limit)));rows=[];counts={}
    omitted=lab.read(lab.DATA/'omitted-videos.json',{})
    for folder in (lab.DATA/'videos').iterdir():
        if not folder.is_dir() or not re.fullmatch('[a-f0-9]{32}',folder.name):continue
        meta=lab.read(folder/'video.json',{})
        excluded=bool(lab.read(folder/'training-excluded.json',{}).get('excluded') or meta.get('sha256') in omitted)
        for a in lab.read(folder/'annotations.json',[]):
            counts[a['label']]=counts.get(a['label'],0)+1
            if label and a['label']!=label:continue
            if search.lower() not in (meta.get('name','')+' '+folder.name).lower():continue
            rows.append(dict(video_id=folder.name,video_name=meta.get('name',folder.name),created=meta.get('created',0),excluded=excluded,annotation={k:a.get(k) for k in ('id','time','label','bounds','frame_index','track_id')}))
    rows.sort(key=lambda r:(-r['created'],r['video_id'],r['annotation'].get('time',0),r['annotation']['id']))
    return dict(items=rows[offset:offset+limit],total=len(rows),offset=offset,limit=limit,labels=counts)

def remove(vid,aid):
    import lab
    folder=lab.video_path(vid);aid=lab.checked_id(aid)
    with lab._per_video_lock(lab._REVIEW_LOCKS,folder):
        with lab.LOCK:
            meta=lab.read(folder/'video.json')
            if not meta:raise ValueError('Video not found')
            annotations=lab.read(folder/'annotations.json',[])
            removed=next((a for a in annotations if a['id']==aid),None)
            if removed is None:raise ValueError('Annotation not found or already removed')
            now=time.time();prior=lab.read(folder/'review.json',{})
            audit=folder/'annotation-history';audit.mkdir(exist_ok=True)
            lab.save(audit/(uuid.uuid4().hex+'.json'),dict(action='remove',epoch=now,annotation=removed,prior_review=prior,source_sha256=meta.get('sha256')))
            # Invalidate approvals before changing labels. Never reinterpret an empty
            # annotation list as a human no-target decision.
            review=dict(completed=False,no_target=False,invalidated_at=now,reason='label_removed',previous_reviewed_at=prior.get('reviewed_at'))
            lab.save(folder/'review.json',review)
            if meta.get('sha256'):
                registry=lab.read(lab.DATA/'reviewed-videos.json',{});registry[meta['sha256']]=review;lab.save(lab.DATA/'reviewed-videos.json',registry)
            sid=meta.get('provenance',{}).get('session_id')
            if sid and re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):
                decision=dict(schema=1,session_id=sid,video_id=vid,source_sha256=meta.get('sha256'),human_confirmed=False,confirmed_anomalous=False,no_target=False,review_required=True,invalidated_epoch=now)
                outbox=lab.DATA/'archive-decisions';outbox.mkdir(exist_ok=True);lab.save(outbox/(sid+'.json'),decision)
                session=lab.STATION/'sessions'/sid
                if (session/'manifest.json').is_file():lab.save(session/'archive-decision.json',decision)
            kept=[a for a in annotations if a['id']!=aid];lab.save(folder/'annotations.json',kept)
            return dict(annotations=kept,removed=aid,review_required=True,saved_models_unchanged=True)
