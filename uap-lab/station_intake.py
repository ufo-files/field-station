"""User-review intake for saved station clips; model/motion suggestions are not labels."""
import threading,time
import lab
_IMPORT_LOCK=threading.Lock()

def import_session(folder):
    with _IMPORT_LOCK:return _import_session(folder)

def _import_session(folder):
    manifest=lab.read(folder/'manifest.json',{})
    if manifest.get('state') not in ('completed','interrupted'):return None
    if manifest.get('validation') or 'migration verification' in manifest.get('title','').lower():return None
    buffer=lab.read(folder/'buffer-state.json',{})
    if manifest.get('buffered_capture') and buffer.get('state')!='assembled':return None
    # Reuse the station's native MP4 remux; do not race it with a CPU transcode.
    if manifest.get('buffered_capture') and (manifest.get('video_playback',{}).get('state')!='completed' or not (folder/'video.mp4').is_file()):return None
    source=folder/'video.mkv'
    if not source.is_file():return None
    meta,created=lab.import_training_file(source)
    target=lab.video_path(meta['id'])
    category='motion-collection' if manifest.get('provisional') else 'motion-collection' if manifest.get('title')=='Three-minute motion training collection' else 'model-detection' if manifest.get('capture_origin')=='lab_model' else 'recorded-clip'
    meta.update(name=manifest.get('title','Recorded clip')+' · '+folder.name,
                provenance=dict(collection=category,session_id=folder.name),recorded_epoch=manifest.get('started_epoch'))
    preview=folder/'video.mp4'
    if preview.is_file() and manifest.get('video_playback',{}).get('state')=='completed':
        if not (target/'preview.mp4').exists():
            try:lab.os.link(preview,target/'preview.mp4')
            except FileExistsError:pass # Another importer already installed the shared preview.
            except OSError:lab.shutil.copyfile(preview,target/'preview.mp4')
        meta['preview_state']='ready'
    lab.save(target/'video.json',meta)
    lab.save(target/'station-evidence.json',dict(session_id=folder.name,native_source_sha256=meta['sha256'],
             rf_log='rf.jsonl',native_timestamps='buffer-segments/frame-times-*.jsonl'))
    # Imported automated postprocessing is not a human review decision.
    review=lab.read(target/'review.json',{})
    if review.get('automated_event') and not review.get('reviewed_at'):
        lab.save(target/'review.json',dict(completed=False,requires_human_review=True))
    return meta

def watch_station():
    while True:
        try:
            index=lab.read(lab.DATA/'station-intake.json',{})
            for folder in sorted((lab.STATION/'sessions').iterdir(),reverse=True):
                if not folder.is_dir() or folder.name in index:continue
                meta=import_session(folder)
                if meta:
                    index[folder.name]=meta['id'];lab.save(lab.DATA/'station-intake.json',index)
                    if meta.get('preview_state')=='preparing':lab.prepare_preview(lab.video_path(meta['id']))
        except Exception as exc:print('Station review intake:',str(exc),flush=True)
        time.sleep(5)
