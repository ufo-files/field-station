"""Public uploads require a completed anomalous web review and both video versions."""
def eligible(manifest,decision=None):
    if manifest.get('validation') or manifest.get('capture_origin')=='validation' or manifest.get('archive_withdrawn'):return False
    decision=decision or {}
    return bool(decision.get('schema')==2 and decision.get('source')=='station_web_ui' and decision.get('session_id')==manifest.get('id') and decision.get('human_confirmed') is True and decision.get('confirmed_anomalous') is True and decision.get('bundle_ready') is True and isinstance(decision.get('videos'),list) and sorted(decision['videos'])==sorted({'video.mp4','video-annotated.mp4'}) and isinstance(decision.get('reviewed_epoch'),(int,float)))
