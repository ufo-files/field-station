"""Automatic 24-hour operational qualification; optical calibration remains separate."""
import hashlib,json,time,os
from pathlib import Path
from spool_events import atomic

def issues(sample,now):
    native=sample['native'];capture=native.get('capture') or {};problems=[]
    if now-native.get('analyzed_epoch',0)>5:problems.append('analysis_stale')
    if native.get('error'):problems.append('analysis_error')
    if native.get('generation_missing_frames',0):problems.append('missing_analysis_frames')
    if native.get('latency_seconds',0)>5:problems.append('analysis_latency_over_5_seconds')
    for key in ['timestamp_gap_count','inferred_missing_frames','overwritten_frames','device_dropped_frames','nonmonotonic_timestamps']:
        if capture.get(key,0):problems.append('capture_'+key)
    if capture.get('captured_frames',0)>120 and not 59<=capture.get('measured_fps',0)<=61:problems.append('capture_cadence_outside_tolerance')
    for receiver in ['narrow','wide']:
        if now-sample.get('rf',{}).get('receivers',{}).get(receiver,{}).get('timestamp',0)>5:problems.append(receiver+'_rf_stale')
    if 'recognition' in sample:
        recognition=sample['recognition']
        if now-recognition.get('updated_epoch',0)>5:problems.append('recognition_stale')
        if recognition.get('error') or not recognition.get('integrity_ok',False):problems.append('recognition_error')
        if now-recognition.get('frame_epoch',0)>5:problems.append('recognition_latency_over_5_seconds')
        if recognition.get('missing_frames',0):problems.append('recognition_missing_frames')
        if recognition.get('classification_errors',0):problems.append('recognition_classification_errors')
    return problems

def interval_sample(sample,previous):
    """Evaluate new counter increments without erasing historical failures."""
    from copy import deepcopy
    current=deepcopy(sample)
    if not previous or previous.get('capture_generation',previous.get('generation'))!=sample['native'].get('capture_generation',sample['native'].get('generation')):return current
    native=current['native'];capture=native.get('capture') or {};old=previous.get('capture') or {}
    for key in ['timestamp_gap_count','inferred_missing_frames','overwritten_frames','device_dropped_frames','nonmonotonic_timestamps']:
        capture[key]=max(0,capture.get(key,0)-old.get(key,0))
    native['generation_missing_frames']=max(0,native.get('generation_missing_frames',0)-previous.get('generation_missing_frames',0))
    elapsed=capture.get('last_pts_seconds',0)-old.get('last_pts_seconds',0)
    if elapsed>0:capture['measured_fps']=(capture.get('captured_frames',0)-old.get('captured_frames',0))/elapsed
    return current

def measurement_sample(data,rf_path,spool,now,recognition_required=False):
    # A journal's embedded camera snapshot can be old while capture remains healthy.
    # Measure current capture independently; retain analysis latency as its own fault.
    data=Path(data);spool=Path(spool)
    native=json.loads((data/'live/native-analysis.json').read_text())
    active=json.loads((spool/'active.json').read_text())['generation']
    native['capture']=json.loads((spool/active/'capture-health.json').read_text())
    native['capture_generation']=active
    sample=dict(epoch=now,native=native,rf=json.loads(Path(rf_path).read_text()))
    if recognition_required:
        sample['recognition']=json.loads((data/'recognition/status.json').read_text())
    return sample

def watch(data,rf_path,stop):
    folder=Path(data)/'qualification';folder.mkdir(exist_ok=True);status_path=folder/'current.json'
    status=json.loads(status_path.read_text()) if status_path.exists() else dict(started_epoch=time.time(),required_seconds=86400,samples=0,failing_samples=0,maximum_latency_seconds=0,scientific_ready=False,limitations=['Independent optical timing, exposure, lens and RF synchronization calibration required','Classifier accuracy and queue throughput not qualified'])
    def fingerprint():
        digest=hashlib.sha256();root=Path(__file__).resolve().parent
        names=['qualification.py','native_frames.py','native_motion.py','native_capture.py','native_journal.py','spool_events.py','spool_export.py','spool_gc.py','requirements.txt']
        names += ['recognition/'+name for name in ['recognition_service.py','recognition_events.py','recognition_store.py','stream_decode.py','stream_decode_worker.py','crop_client.py','native_tracks.py','config.json']]
        for name in names:
            path=root/name
            if path.exists():digest.update(name.encode());digest.update(path.read_bytes())
        digest.update(os.environ.get('CAPTURE_FFMPEG','').encode());return digest.hexdigest()
    configuration_id=fingerprint();changed=status.get('configuration_id')!=configuration_id
    if changed:status.update(configuration_id=configuration_id,clean_since_epoch=None,clean_seconds=0,configuration_started_epoch=time.time())
    while not stop.wait(10):
        now=time.time()
        try:
            latest=fingerprint()
            if latest!=configuration_id:
                configuration_id=latest;changed=True;status.update(configuration_id=latest,clean_since_epoch=None,clean_seconds=0,configuration_started_epoch=now)
            recognition_config=Path(__file__).resolve().parent/'recognition/config.json';recognition_required=recognition_config.exists() and json.loads(recognition_config.read_text()).get('event_owner');sample=measurement_sample(data,rf_path,os.environ['CAPTURE_BUFFER_ROOT'],now,recognition_required);native=sample['native'];faults=issues(interval_sample(sample,status.get('previous_native')),now)
            if changed:faults.append('configuration_changed');changed=False
            if now-(native.get('capture') or {}).get('last_frame_epoch',0)>5:faults.append('capture_stale')
            if status.get('previous_native') and status['previous_native'].get('capture_generation',status['previous_native'].get('generation'))!=native.get('capture_generation',native.get('generation')):faults.append('capture_restarted')
            status['previous_native']={key:native.get(key) for key in ['generation','capture_generation','capture','generation_missing_frames']}
            status['historical_capture_counters']=native.get('capture')
            status.update(updated_epoch=now,samples=status['samples']+1,failing_samples=status['failing_samples']+bool(faults),current_faults=faults,maximum_latency_seconds=max(status['maximum_latency_seconds'],native.get('latency_seconds',0)),elapsed_seconds=now-status['started_epoch'],generation=native.get('generation'))
            if faults or now-status.get('last_sample_epoch',now)>30:status['clean_since_epoch']=None
            elif status.get('clean_since_epoch') is None:status['clean_since_epoch']=now
            status['last_sample_epoch']=now
            status['clean_seconds']=now-status['clean_since_epoch'] if status.get('clean_since_epoch') is not None else 0
            status['state']='fault' if faults else 'operational_checks_passed' if status['clean_seconds']>=status['required_seconds'] else 'qualifying'
            status['scientific_ready']=False
            day=time.strftime('%Y%m%d',time.gmtime(now))
            with (folder/(day+'.jsonl')).open('a') as log:log.write(json.dumps(dict(epoch=now,configuration_id=configuration_id,journal_queue=native.get('journal_queue_frames',0),journal_lag=native.get('journal_lag_seconds',0),generation=native.get('generation'),analyzed=native.get('analyzed_frames'),generation_analyzed=native.get('generation_analyzed_frames'),captured=(native.get('capture') or {}).get('captured_frames'),missing=native.get('generation_missing_frames'),latency=native.get('latency_seconds'),backlog=native.get('backlog_frames'),faults=faults))+'\n')
            atomic(status_path,status)
        except Exception as exc:
            status.update(state='measurement_error',error=str(exc),updated_epoch=now,clean_since_epoch=None,clean_seconds=0);atomic(status_path,status)
