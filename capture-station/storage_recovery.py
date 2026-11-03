"""Persisted free-space hysteresis for automatic camera recovery."""
def update_pause(storage,reserve,previous=None):
 previous=previous or {}
 # Refill ten percent of the reserve (at least 10 GiB) before restarting capture.
 resume=reserve+max(10*1024**3,reserve*.1)
 paused=bool(previous.get('paused'))
 if storage.get('available'):
  if storage['free']<reserve:paused=True
  elif paused and storage['free']>=resume:paused=False
 return dict(paused=paused,reserve_bytes=reserve,resume_bytes=resume,free_bytes=storage.get('free'),available=storage.get('available',False))
