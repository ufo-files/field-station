"""Compact, accessible table for retained training reports."""
import html,time

def render(reports,automatic=True):
 esc=lambda value:html.escape(str(value),quote=True)
 def accuracy(value):
  total=value.get('total',0)
  return f"{100*sum(m.get('tp',0) for m in value.get('per_class',{}).values())/total:.1f}%" if total else '—'
 statuses={'deployed':'Released','validated_no_improvement':'Earlier model kept','validated_unchanged':'Unchanged','rejected':'Not released','rolled_back':'Rolled back','error':'Failed','maintenance':'Preparing','superseded':'Labels changed'}
 rows=[]
 for record in reports:
  started=record.get('started_epoch');finished=record.get('finished_epoch');evaluation=record.get('evaluation',{});labels=record.get('labels',{})
  stamp=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(started)) if started else ''
  date=('<time datetime="'+stamp+'">'+time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(started))+'</time>') if started else '—'
  duration='—'
  if started and finished:
   seconds=max(0,int(finished-started));duration=f'{seconds//60}m {seconds%60:02d}s'
  phase=record.get('phase','unknown');status=statuses.get(phase,phase.replace('_',' ').capitalize())
  detail='<p>'+esc(record.get('reason') or record.get('error') or 'No additional details recorded.')+'</p>'
  if labels:detail+='<p>Reviewed labels: '+esc(', '.join(f'{k.replace("_"," ")}: {v:,}' for k,v in labels.items()))+'</p>'
  if evaluation.get('reasons'):detail+='<p>'+esc('; '.join(map(str,evaluation['reasons'])))+'</p>'
  classes=evaluation.get('candidate',{}).get('per_class',{});baseline=evaluation.get('baseline',{}).get('per_class',{})
  if classes:
   detail+='<table class="class-results"><thead><tr><th>Category</th><th>Correct</th><th>False positives, previous → candidate</th></tr></thead><tbody>'
   for label,metric in classes.items():
    detail+='<tr><td>'+esc(label.replace('_',' '))+'</td><td>'+esc(str(metric.get('tp',0))+'/'+str(metric.get('tp',0)+metric.get('fn',0)))+'</td><td>'+esc(str(baseline.get(label,{}).get('fp','—'))+' → '+str(metric.get('fp','—')))+'</td></tr>'
   detail+='</tbody></table>'
  validation=('Passed' if evaluation['passed'] else 'Failed') if 'passed' in evaluation else '—'
  cells=[date,esc(status),f"{sum(labels.values()):,}" if labels else '—',accuracy(evaluation.get('candidate',{})),accuracy(evaluation.get('baseline',{})),validation,duration,'<details><summary>Details</summary>'+detail+'</details>']
  rows.append('<tr>'+''.join('<td>'+cell+'</td>' for cell in cells)+'</tr>')
 return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Training history · Field Station</title><link rel="stylesheet" href="/style.css"><style>
 body:has(main.training-history){height:100dvh;overflow:hidden}main.training-history{width:100%;max-width:none;height:calc(100dvh - 64px);margin:0;padding:0;display:flex;flex-direction:column}.training-history h1{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}.history-scroll{flex:1;min-height:0;overflow:auto;border:0;border-radius:0;margin:0}table{width:100%;border-collapse:separate;border-spacing:0;text-align:left;font-size:14px}#trainingHistory{min-width:1000px}#trainingHistory>thead>tr>th{position:sticky;top:0;z-index:2;box-shadow:0 1px 0 var(--line)}th{font-weight:600;background:var(--panel)}th,td{padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:top}tbody tr:last-child>td{border-bottom:0}tbody tr:hover{background:var(--panel)}td:not(:last-child){white-space:nowrap;font-variant-numeric:tabular-nums}details{margin:0;min-width:90px}details[open]{min-width:330px;max-width:480px}summary{cursor:pointer;color:var(--accent)}details p{white-space:normal;line-height:1.5}.class-results{font-size:12px}.class-results th,.class-results td{white-space:normal;padding:8px}.history-links{flex:none;margin:0;padding:12px 14px;font-size:14px;border-top:1px solid var(--line)}@media(max-width:600px){th,td{padding:10px}}
 </style></head><body><main class="training-history"><h1>Training history</h1><div class="history-scroll" role="region" aria-label="Training history table" tabindex="0"><table id="trainingHistory"><thead><tr>"""+''.join('<th scope="col">'+name+'</th>' for name in ('Started','Result','Reviewed frames','Candidate','Previous model','Validation','Duration','Details'))+"""</tr></thead><tbody>"""+(''.join(rows) or '<tr><td colspan="8">No training runs recorded yet.</td></tr>')+"""</tbody></table></div><p class="history-links"><a href="/metrics">Model metrics</a> · <a href="/api/training-history">Download history JSON</a></p></main><script>document.querySelectorAll('time[datetime]').forEach(el=>{el.title=el.textContent;el.textContent=new Date(el.dateTime).toLocaleString();});</script></body></html>"""
