"""Durable provisional review queue. No negative-result deletion is authorized by confidence alone."""
import threading,time,fcntl,subprocess,sys
import lab

def listing():
    jobs=[]
    for path in (lab.STATION/'sessions').glob('*/provisional.json'):
        job=lab.read(path,{})
        job.update(lab.read(lab.DATA/'provisional-queue'/(path.parent.name+'.json'),{}))
        manifest=lab.read(path.parent/'manifest.json',{})
        jobs.append(dict(job,recording_state=manifest.get('state'),started_epoch=manifest.get('started_epoch'),pre_roll_actual_seconds=manifest.get('pre_roll_actual_seconds')))
    return sorted(jobs,key=lambda j:j.get('created',0),reverse=True)

def recover_dispatcher(rid):
    if not lab.os.environ.get('UAP_LAB_WORKER_CONFIG'):return
    folder=lab.DATA/'runs'/rid
    with (folder/'dispatcher.lock').open('a') as lease:
        try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        with (folder/'dispatcher.log').open('ab') as log:
            subprocess.Popen([sys.executable,str(lab.ROOT/'dispatch_job.py'),rid],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)

def tick():
    from station_intake import import_session
    from review_archive import sync_decisions
    sync_decisions()
    jobs=listing();queue_folder=lab.DATA/'provisional-queue';queue_folder.mkdir(exist_ok=True)
    existing=[lab.read(p,{}) for p in (lab.DATA/'runs').glob('*/run.json')]
    busy=any(r.get('detached') and r.get('state') not in ('complete','failed') for r in existing)
    models={}
    def persist(path,job):
        if lab.read(path,{})!=job:lab.save(path,job)
    for job in reversed(jobs):
        folder=lab.STATION/'sessions'/job['session_id'];path=queue_folder/(job['session_id']+'.json')
        if job['recording_state']=='recording':continue
        if job.get('state') in ('review_required','confirmed_anomalous','discarded'):continue
        if job.get('run_id'):
            run=lab.read(lab.DATA/'runs'/job['run_id']/'run.json',{})
            if run.get('state')=='complete':
                # Appearance matches are suggestions. Human review remains necessary
                # until held-out validation supports automatic acceptance/rejection.
                job.update(state='review_required',classification='model_match' if run.get('detected_frames',0) else 'no_model_match',processed_frames=run.get('processed_frames',run.get('frame_count')),frame_count=run.get('frame_count'))
            elif run.get('state')=='failed':job.update(state='analysis_failed',error=run.get('error'),classification='unclassified')
            else:
                job.update(state='analyzing',worker_state=run.get('state','unknown'))
                if run and time.time()>=run.get('retry_after_epoch',0):recover_dispatcher(job['run_id'])
            persist(path,job);continue
        model_key=job.get('model_id')
        if model_key not in models:models[model_key]=lab.read(lab.DATA/'models'/str(model_key)/'model.json') or lab.read(lab.DATA/'active-model.json')
        model=models[model_key]
        if not model:
            job.update(state='waiting_model');persist(path,job);continue
        # Resume by recorded run provenance if the process stopped between launch
        # and saving the returned run ID. Never blindly submit the same clip twice.
        meta=lab.read(lab.video_path(job['video_id'])/'video.json') if job.get('video_id') else None
        if meta is None:meta=import_session(folder)
        if not meta:continue
        job.update(video_id=meta['id'],model_id=model['id'],state='queued')
        run=next((r for r in existing if r.get('video_id')==meta['id'] and r.get('model_id')==model['id']),None)
        if run:
            job.update(run_id=run['id'],state='analyzing');persist(path,job);continue
        from recognition_queue import local_summary
        try:local=local_summary(meta)
        except (OSError,ValueError) as exc:
            job.update(state='local_analysis_error',error=str(exc),classification='unclassified',automatic_deletion=False);persist(path,job);continue
        if local is not None:
            job.update(local);job.pop('error',None);persist(path,job)
            if local['state']=='review_required':return # Bound new alignment work to one clip per pass.
            continue
        if not lab.os.environ.get('UAP_LAB_WORKER_CONFIG'):
            job.update(state='waiting_worker',message='M6 worker is not configured; original evidence retained locally.')
        elif busy:
            job.update(state='queued',message='Waiting for the current model-classification job')
        else:
            try:
                job.update(run_id=lab.start_run(meta['id'],.97,['anomalous'],model=model),state='analyzing');busy=True
            except ValueError as exc:job.update(state='queued',message=str(exc))
        persist(path,job)

def watch():
    while True:
        try:tick()
        except Exception as exc:print('Provisional queue:',str(exc),flush=True)
        time.sleep(5)
