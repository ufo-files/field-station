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
 cards=[]
 esc=lambda v:html.escape(str(v))
 for r in reports[:48]:
  cleanup=r.get('maintenance',{});m=cleanup.get('metrics',{});ev=r.get('evaluation',{});states=m.get('delivery',{})
  classes=ev.get('candidate',{}).get('per_class',{});previous=ev.get('baseline',{}).get('per_class',{});table=[]
  for label,metric in classes.items():
   old=previous.get(label,{})
   table.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (label,str(old.get('tp','—'))+'/'+str(old.get('tp',0)+old.get('fn',0)),str(metric['tp'])+'/'+str(metric['tp']+metric['fn']),str(old.get('fp','—'))+' → '+str(metric['fp'])))+'</tr>')
  cards.append('<section><h2>Hour '+str(r['slot'])+' · '+time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(r['started_epoch']))+'</h2><p><strong>'+esc(r.get('phase'))+'</strong> '+esc(r.get('reason') or r.get('error') or '')+'</p><dl>'+''.join('<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>' for k,v in (
   ('Candidates in preceding hour',m.get('candidates',0)),('Emails pending before cleanup',states.get('pending',0)),('Accepted by Mail',states.get('accepted_by_mail',0)),('Emails retired',cleanup.get('cancelled_alerts',0)),('Video storage freed',str(round(cleanup.get('videos',{}).get('unlinked_bytes',0)/1e9,1))+' GB'),('Raw frames skipped',cleanup.get('raw',{}).get('discarded',{}).get('frames',0)),('Analysis delay before cleanup',str(round(m.get('health',{}).get('latency_seconds') or 0,1))+' s')))+ '</dl><p>Training labels: '+esc(', '.join(str(v)+' '+k for k,v in r.get('labels',{}).items()) or 'Pending')+'</p><p>Reviewed candidate labels: '+esc(', '.join(str(v)+' '+k for k,v in m.get('review_labels',{}).items()) or 'None yet')+' (reviewed subset only).</p><p>Validation: '+esc('Passed' if ev.get('passed') else 'Failed' if 'passed' in ev else 'Pending')+'</p>'+('<div class="scroll"><table><tr><th>Class</th><th>Previous correct / total</th><th>Candidate correct / total</th><th>False positives: previous → candidate</th></tr>'+''.join(table)+'</table></div>' if table else '')+'</section>')
 body='''<!doctype html><html lang="en"><meta name="viewport" content="width=device-width"><meta charset="utf-8"><title>Provisional training</title><style>body{font:16px system-ui;margin:24px auto;padding:0 16px;max-width:1000px;background:#111;color:#eee}a{color:#8cf}section{border:1px solid #555;border-radius:12px;padding:20px;margin:24px 0}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #555;text-align:left}p{line-height:1.5;overflow-wrap:anywhere}.scroll{overflow:auto}dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}dt{color:#aaa;font-size:14px}dd{margin:4px 0;font-size:24px}h2{font-size:20px}</style><h1>Provisional training</h1><p>Ends '''+time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(controller.c['provisional']['end_epoch']))+'''. Cycles run hourly from the start time. Showing the latest 48 reports; the JSON history includes every hour.</p><p>Candidate counts are model flags, not confirmed anomalies. Fewer emails or deleted footage do not demonstrate improved accuracy. Compare held-out results below. Hour 0 is the starting baseline, covering the preceding hour. Skipped raw frames were not analyzed.</p><p><a href="/">Back to field station</a> · <a href="/api/training-history">JSON history</a></p>'''+''.join(cards)+'</html>'
 (root/'report.html').write_text(body)
 # Only report artifacts are written; the station runtime is unaffected.
 controller.remote(['mkdir','-p',controller.c['remote_lab']+'/provisional-training'],timeout=30)
 for name in ('history.json','report.html'):
  with (root/name).open('rb') as f:controller.remote([controller.python,'-c','import pathlib,sys; p=pathlib.Path(sys.argv[1]); t=p.with_suffix(".upload"); t.write_bytes(sys.stdin.buffer.read()); t.replace(p)',controller.c['remote_lab']+'/provisional-training/'+name],stdin=f,timeout=30)
 record['published']=True;save(root/(str(record['slot'])+'.json'),record)

def tick(controller):
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
  record['maintenance']=controller.rpc('provisional_station.py','--slot',str(hour))
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
