"""Browse current annotations; audit removals and invalidate stale review decisions."""
import time, re, uuid

def preserved_root():
    import lab, os
    from pathlib import Path
    return Path(os.environ.get('UAP_LAB_PRESERVED_DATA',str(Path(__file__).resolve().parent.parent/'preserved/uap-lab')))

def gallery_image(kind,vid,aid):
    import lab
    vid=lab.checked_id(vid);aid=lab.checked_id(aid)
    if kind=='review':
        folder=lab.DATA/'email-reviews/examples'/aid
        record=lab.read(folder/'review.json',{})
        if record.get('event_id')!=vid or record.get('deleted'):raise ValueError('Review not found')
        path=folder/'native-object.png'
    else:
        if kind not in ('video','preserved'):raise ValueError('Invalid source')
        folder=(lab.DATA if kind=='video' else preserved_root())/'videos'/vid
        annotation=next((a for a in lab.read(folder/'annotations.json',[]) if a['id']==aid),None)
        if not annotation:raise ValueError('Annotation not found')
        path=folder/annotation['image']
    if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()) or path.suffix.lower() not in ('.png','.jpg','.jpeg'):raise ValueError('Invalid image')
    return path

def listing(label='',search='',offset=0,limit=100,video=''):
    import lab
    from urllib.parse import urlencode
    from email_training import canonical_label
    label=canonical_label(label)
    offset=max(0,int(offset));limit=max(1,min(100,int(limit)));rows=[];counts={};seen=set();videos={};groups={'anomalous_field_station':0,'pursue':0}
    omitted=lab.read(lab.DATA/'omitted-videos.json',{})
    def add(row):
        a=row['annotation'];key=row['kind']+':'+row['video_id'];videos[key]=row['video_name']
        if video and key!=video:return
        if search.lower() not in (row['video_name']+' '+row['video_id']+' '+row['source_name']).lower():return
        counts[a['label']]=counts.get(a['label'],0)+1
        field_anomaly=a['label']=='anomalous' and row.get('field_station',False)
        if field_anomaly:groups['anomalous_field_station']+=1
        pursue=row.get('collection')=='PURSUE'
        if pursue:groups['pursue']+=1
        if label=='pursue':
            if not pursue:return
        elif label=='anomalous_field_station':
            if not field_anomaly:return
        elif label and a['label']!=label:return
        row['image_url']='/api/labeled-image?'+urlencode(dict(source=row['kind'],id=row['video_id'],annotation=a['id']))
        rows.append(row)
    for kind,root in (('video',lab.DATA),('preserved',preserved_root())):
        root_omitted=omitted if kind=='video' else lab.read(root/'omitted-videos.json',{})
        for folder in (root/'videos').glob('*'):
            if not folder.is_dir() or not re.fullmatch('[a-f0-9]{32}',folder.name):continue
            annotations=lab.read(folder/'annotations.json',[])
            if not annotations:continue
            meta=lab.read(folder/'video.json',{})
            # The current library is authoritative, including removals.
            if kind=='preserved' and (lab.DATA/'videos'/folder.name/'video.json').exists():continue
            excluded=bool(lab.read(folder/'training-excluded.json',{}).get('excluded') or meta.get('sha256') in omitted or meta.get('sha256') in root_omitted)
            provenance=meta.get('provenance',{});review=lab.read(folder/'review.json',{})
            station_source=provenance.get('collection')!='PURSUE' and (bool(re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',str(provenance.get('session_id','')))) or provenance.get('collection') in ('live-event','recorded-clip','model-detection','motion-collection'))
            human_labels=not review.get('automated_event') or bool(review.get('reviewed_at'))
            for a in annotations:
                key=(meta.get('sha256') or folder.name,a['id'])
                if key in seen:continue
                seen.add(key)
                add(dict(video_id=folder.name,video_name=meta.get('name',folder.name),created=meta.get('created',0),excluded=excluded,kind=kind,field_station=bool(station_source and human_labels),collection=provenance.get('collection'),source_name=meta.get('provenance',{}).get('collection','Video labels'),original_available=(folder/'source').is_file(),source_page=meta.get('provenance',{}).get('source_page'),annotation={k:a.get(k) for k in ('id','time','label','bounds','frame_index','track_id')}))
    for path in (lab.DATA/'email-reviews/examples').glob('*/review.json'):
        r=lab.read(path,{})
        if r.get('deleted') or not r.get('human_confirmed'):continue
        event=r.get('event_id','');sample=path.parent.name
        if not re.fullmatch('[a-f0-9]{32}',event) or not re.fullmatch('[a-f0-9]{32}',sample):continue
        add(dict(video_id=event,video_name='Alert '+event[:8],created=r.get('reviewed_epoch',0),excluded=not r.get('multiclass_ready',False),kind='review',field_station=r.get('source') in ('owner_email_reply','station_web_review'),source_name='Email reply' if r.get('source')=='owner_email_reply' else 'Web alert review',original_available=False,review_url='/email-review?id='+event,annotation=dict(id=sample,time=r.get('review_clip_time',0),label=r.get('label','unknown'),bounds=None,track_id=None)))
    rows.sort(key=lambda r:(-r['created'],r['video_id'],r['annotation'].get('time',0),r['annotation']['id']))
    return dict(items=rows[offset:offset+limit],total=len(rows),offset=offset,limit=limit,labels=counts,videos=videos,groups=groups)

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
