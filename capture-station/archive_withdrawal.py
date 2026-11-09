"""Withdraw public bundles only on explicit, persisted human corrections.

Never infer a negative label from missing media, a missing review, or a pending
export. Local training examples and source evidence are not deleted here.
"""
import hashlib,json,time
from pathlib import Path
from experiments import load

def correction(folder,data,records):
    manifest=load(folder/'manifest.json',{})
    segments=load(folder/'buffer-state.json',{}).get('segments',[])
    annotations=load(folder/'review-annotations.json',{}).get('annotations',[])
    original=[a for a in annotations if a.get('label')=='anomalous']
    if not original or not segments or not manifest.get('spool_generation'):return None
    start,end=segments[0]['start'],segments[-1]['end'];generation=manifest['spool_generation']
    reviewed=[r for r in records if r.get('source')=='station_web_review' and r.get('human_confirmed') is True and not r.get('deleted')]
    in_session=[r for r in reviewed if r.get('generation')==generation and start<=r.get('pts_seconds',-1)<end]
    if any(r.get('label')=='anomalous' for r in in_session):return None
    by_id={(r.get('event_id'),r.get('sample_id',r.get('event_id'))):r for r in reviewed}
    proof=[]
    for annotation in original:
        key=(annotation.get('review_id'),annotation.get('annotation_id'))
        current=by_id.get(key)
        if current is None:
            # Full-video reviews have their own annotations and completed flag.
            video=data/'videos'/str(key[0]);meta=load(video/'video.json',{})
            if meta.get('provenance',{}).get('session_id')!=folder.name or not load(video/'review.json',{}).get('completed'):return None
            rows=load(video/'annotations.json',[])
            if any(r.get('label')=='anomalous' for r in rows):return None
            current=next((r for r in rows if r.get('id')==key[1]),None)
        if not current or current.get('label')!='not_anomalous':return None
        proof.append(dict(review_id=key[0],annotation_id=key[1],reviewed_epoch=current.get('reviewed_epoch'),label=current['label']))
    return dict(reason='Human review corrected all anomalous annotations to not anomalous',proof=proof,
                revision=hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest())

def reconcile(archive):
    data=archive.data.parent/'uap-lab'
    manifest=data/'email-reviews/training-manifest.json'
    records=load(manifest,{}).get('examples')
    if not isinstance(records,list):return
    processed=0
    for job in list(archive.job_cache.values()):
        if job.get('manual_scope'):continue # Explicit manual publication is independent of object classifications.
        if not job.get('identifier'):continue
        folder=archive.folder(job['id']);request=job.get('withdrawal',{})
        proof=correction(folder,data,records)
        if proof and job['state'] not in ('withdrawing','withdrawn'):
            job.update(state='withdrawing',withdrawal=dict(proof,previous_state=job['state'],requested_epoch=time.time()),next_attempt=0,error=None)
            archive.persist(job);archive.publish(job)
        elif job['state']=='withdrawing' and not proof and not request.get('task_id'):
            job.update(state=request.get('previous_state','held_for_review'),error=None);job.pop('withdrawal',None)
            archive.persist(job);archive.publish(job)
        if job['state'] not in ('withdrawing','withdrawn'):continue
        request=job['withdrawal']
        # A later anomalous correction must be fully exported before restoring.
        restore=not proof and archive.archive_eligible(job['id'])
        if job['state']=='withdrawn' and not restore:continue
        if request.get('retry_epoch',0)>time.time():continue
        try:
            if restore:
                if not request.get('restore_task_id'):
                    request['restore_task_id']=archive.api.visibility(job,False)
                    request['retry_epoch']=time.time()+30
                else:
                    metadata=archive.api.metadata(job['identifier'])
                    if metadata.get('metadata') and not metadata.get('is_dark'):
                        job.update(state='queued',plan_version=0,verified_at=None,next_attempt=0,error=None,file_index=0,parts=[],uploaded_bytes=0)
                        job.pop('upload_id',None)
                        job.pop('withdrawal',None)
                        archive.complete_session_plan(job,load(folder/'manifest.json',{}))
                    else:request['retry_epoch']=time.time()+30
            elif not request.get('task_id'):
                # Recheck current durable labels immediately before publication change.
                latest=load(manifest,{}).get('examples',[])
                if not correction(folder,data,latest):continue
                request['task_id']=archive.api.visibility(job,True)
                request['retry_epoch']=time.time()+30
            else:
                metadata=archive.api.metadata(job['identifier'])
                if metadata.get('is_dark') or not metadata:
                    job.update(state='withdrawn',withdrawn_at=time.time(),error=None)
                else:request['retry_epoch']=time.time()+30
            archive.persist(job);archive.publish(job)
        except (OSError,ValueError) as error:
            job['error']=str(error);request['retry_epoch']=time.time()+60
            archive.persist(job);archive.publish(job)
        processed+=1
        if processed>=5:return # Bound each pass while draining correction batches promptly.
