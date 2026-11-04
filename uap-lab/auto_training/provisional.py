"""Time-limited hourly training schedule and durable, comparable reports."""
import html,json,time
from pathlib import Path

def slot(config,now):
 p=config.get('provisional',{})
 if not p.get('enabled') or not p['start_epoch']<=now<p['end_epoch']:return None
 return int((now-p['start_epoch'])//3600)

def compact_evaluation(report):
 return {k:({a:b for a,b in v.items() if a!='predictions'} if isinstance(v,dict) else v) for k,v in report.items() if k in ('passed','reasons','baseline_version','candidate_version','baseline','candidate')}

def publish(controller,record):
 root=controller.root/'provisional';root.mkdir(exist_ok=True)
 from controller import save,read
 save(root/(str(record['slot'])+'.json'),record)
 reports=[read(p) for p in root.glob('*.json') if p.stem.isdigit()]
 reports.sort(key=lambda r:r['slot'],reverse=True)
 summary=dict(period=controller.c['provisional'],hours=reports)
 save(root/'history.json',summary)
 from training_history import render
 body=render(reports,automatic=controller.c.get('automatic_training_enabled') is not False)
 (root/'report.html').write_text(body)
 # Only report artifacts are written; the station runtime is unaffected.
 controller.remote(['mkdir','-p',controller.c['remote_lab']+'/provisional-training'],timeout=30)
 for name in ('history.json','report.html'):
  with (root/name).open('rb') as f:controller.remote([controller.python,'-c','import pathlib,sys; p=pathlib.Path(sys.argv[1]); t=p.with_suffix(".upload"); t.write_bytes(sys.stdin.buffer.read()); t.replace(p)',controller.c['remote_lab']+'/provisional-training/'+name],stdin=f,timeout=30)
 record['published']=True;save(root/(str(record['slot'])+'.json'),record)

def tick(controller):
 if controller.c.get("automatic_training_enabled") is False:
  controller.notify_release();controller.recover();return
 from controller import read,save
 hour=slot(controller.c,time.time())
 if hour is None:return controller.tick()
 root=controller.root/'provisional';root.mkdir(exist_ok=True);path=root/(str(hour)+'.json');record=read(path,{})
 controller.notify_release();controller.recover()
 if record.get('complete'):
  if not record.get('published'):publish(controller,record)
  return
 if not record:record=dict(slot=hour,started_epoch=time.time(),phase='maintenance')
 save(path,record)
 try:
  # Recover interrupted activation before stopping services for maintenance.
  record['maintenance']=dict(complete=True,policy='capacity_verified_offload') if controller.c.get('capacity_retention') else controller.rpc('provisional_station.py','--slot',str(hour))
  save(path,record)
  controller.provisional_slot=hour
  controller.tick()
  record.update(phase=controller.state['phase'],labels=controller.state.get('labels',{}),candidate_version=controller.state.get('candidate_version'),reason=controller.state.get('reason'),deferred_labels=controller.state.get('deferred_labels',[]),complete=True)
  folder=controller.state.get('run_directory')
  if folder:record['evaluation']=compact_evaluation(read(Path(folder)/'promotion-evaluation.json',{}))
 except Exception as exc:
  record.update(phase='error',error=str(exc))
  # Maintenance retries within the hour; once it succeeded, failures do not
  # trigger endless repeated training or cleanup of newly arriving footage.
  record['complete']=bool(record.get('maintenance',{}).get('complete'))
  raise
 finally:
  record['finished_epoch']=time.time();publish(controller,record)


def compatible_reviews(previous,current):
 """New labels wait for the next hour; corrections/deletions invalidate a run."""
 newest={r['origin']:r for r in current}
 for row in previous:
  fresh=newest.get(row['origin'])
  if fresh is None or any(fresh.get(k)!=row.get(k) for k in ('label','pixel_sha256','group')):return False
 old_pixels={r['pixel_sha256']:r['label'] for r in previous}
 return all(r['pixel_sha256'] not in old_pixels or old_pixels[r['pixel_sha256']]==r['label'] for r in current)
