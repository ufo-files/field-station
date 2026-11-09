"""Repair a lagging event journal from contiguous, durable recognition results."""
import json,sqlite3,time
from pathlib import Path
from spool_events import atomic

def recover_event_journal(journal,store_path,recognition_state):
 previous=journal.previous
 if not previous or previous['generation']==recognition_state['generation']:return 0
 folder=journal.root/previous['generation']
 if not (folder/'closed.json').exists():return 0
 try:ack=json.loads((folder/'recognition-ack.json').read_text())
 except FileNotFoundError:return 0
 if ack.get('generation')!=previous['generation'] or not ack.get('integrity_ok'):return 0
 first=previous['last_sequence']+1;last=ack['last_sequence']
 if first>last:return 0
 paths=[Path(store_path),*sorted((Path(store_path).parent/'partitions').glob('*.sqlite'))]
 connections=[]
 try:
  connections=[sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5) for p in paths]
  expected=first
  while expected<=last:
   batch={}
   for db in connections:
    for row in db.execute('SELECT sequence,pts,epoch,model,observations FROM frames WHERE generation=? AND sequence>=? AND sequence<=? ORDER BY sequence LIMIT 256',(previous['generation'],expected,last)):
     if row[0] in batch and batch[row[0]]!=row:raise ValueError('Conflicting durable recognition records during journal recovery')
     batch[row[0]]=row
   ordered=sorted(batch.values())[:256]
   if not ordered or ordered[0][0]!=expected:raise ValueError('Missing durable recognition frame during journal recovery; evidence retained')
   for sequence,pts,epoch,model,raw in ordered:
    if sequence!=expected:break
    observations=json.loads(raw);boxes=[o['box'] for o in observations]
    state=dict(journal.previous,phase='analyzing',error=None,last_sequence=sequence,last_pts_seconds=pts,analyzed_epoch=time.time(),analyzed_frames=journal.previous.get('analyzed_frames',0)+1,generation_analyzed_frames=journal.previous.get('generation_analyzed_frames',0)+1)
    timing=dict(sequence=sequence,pts_seconds=pts,received_epoch=epoch)
    journal.process((timing,boxes,{},previous['generation'],model,state));expected+=1
  if abs(journal.previous['last_pts_seconds']-ack['last_pts_seconds'])>.003:raise ValueError('Recovered journal does not match durable recognition acknowledgment')
  audit=dict(generation=previous['generation'],first_sequence=first,last_sequence=last,last_pts_seconds=journal.previous['last_pts_seconds'],frames=last-first+1,source='durable_recognition_results',global_motion_metrics_available=False,recovered_epoch=time.time())
  # Older recognition rows retain object boxes, but not the global-change bit.
  # Record that limitation rather than claiming to reconstruct that signal.
  atomic(folder/'analysis-recovery.json',audit)
  journal.previous=dict(journal.previous,journal_recovery=audit)
  journal.persist()
  return last-first+1
 finally:
  for db in connections:db.close()
