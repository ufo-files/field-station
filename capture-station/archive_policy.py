"""Public archive scope: explicit manual recordings or confirmed anomalies."""
def eligible(manifest,decision=None):
    if manifest.get('validation') or manifest.get('capture_origin')=='validation':return False
    if manifest.get('capture_origin') in ('manual','lab_model'):return True
    decision=decision or {}
    return bool(decision.get('schema')==1 and decision.get('session_id')==manifest.get('id') and decision.get('human_confirmed') is True and decision.get('confirmed_anomalous') is True and isinstance(decision.get('reviewed_epoch'),(int,float)))
