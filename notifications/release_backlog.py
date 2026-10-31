"""Retire unsent pre-release alerts, preserving their evidence and all training data."""
import time
from pathlib import Path
from mail_alerts import read,save
TERMINAL={'accepted_by_mail','submitting','uncertain','cancelled','suppressed','expired'}

def cancel_if_obsolete(folder,event,release):
 if not release or release.get('state')!='deployed' or not release.get('health_verified'):return None
 if event.get('model')==release['version']:return None
 if not release.get('clear_candidate_backlog') and time.time()-event.get('created_epoch',event.get('detected_epoch',time.time()))<48*3600:return None
 # A later candidate can emit observations while being evaluated; a previous release
 # must not delete that future candidate's queue.
 if event.get('created_epoch',event.get('detected_epoch',float('inf')))>release['deployed_epoch']:return None
 path=folder/'delivery.json';previous=read(path,{})
 if previous.get('state') in TERMINAL:return None
 receipt=dict(state='cancelled',reason='Superseded by successfully released model',superseding_model=release['version'],release_epoch=release['deployed_epoch'],updated_epoch=time.time(),previous_delivery=previous)
 save(path,receipt);return receipt

def latest(config):return read(Path(config['outbox']).parent/'active-model-release.json',{}) if config.get('outbox') else {}

def clear(config):
 release=latest(config)
 if not release or release.get('state')!='deployed' or not release.get('health_verified'):return
 root=Path(config['outbox']);audit=root.parent/'model-releases'/release['version']/'backlog-cleanup.json'
 if read(audit,{}).get('complete'):return
 cancelled=[]
 for marker in sorted(root.glob('*/event.json')):
  event=read(marker,{})
  if cancel_if_obsolete(marker.parent,event,release):cancelled.append(marker.parent.name)
  elif read(marker.parent/'delivery.json',{}).get('superseding_model')==release['version']:cancelled.append(marker.parent.name)
 save(audit,dict(complete=True,version=release['version'],cancelled_alerts=len(cancelled),event_ids=cancelled,updated_epoch=time.time(),preserved='All saved evidence, reviews and training data'))
