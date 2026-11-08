'use strict';
(()=>{
 const body=document.getElementById('modelRows'),rows=new Map();let token,benchmark,busy=false;
 const pct=v=>typeof v==='number'?(v*100).toFixed(1)+'%':'—';
 const date=v=>v?new Date(v*1000).toLocaleString():'—';
 function notice(message,error=false){if(window.stationNotifications)window.stationNotifications.set('modelTestNotice',message,error);else{const n=document.getElementById('notice');n.textContent=message;n.classList.toggle('error',error)}}
 async function api(method='GET',value){const r=await fetch('/api/model-tests',{method,headers:value?{'Content-Type':'application/json','X-Lab-Token':token}:{},body:value?JSON.stringify(value):undefined,signal:AbortSignal.timeout(15000)});const data=await r.json();if(!r.ok)throw Error(data.error||'Model tests are unavailable');return data}
 function render(data){
  token=data.token;benchmark=data.benchmark;
  document.getElementById('benchmarkSummary').textContent=benchmark?`${benchmark.count} training frames · Shared sample ${benchmark.id.slice(0,8)}`:'Preparing the shared evaluation sample…';
  if(!data.models.length){body.replaceChildren();const tr=body.insertRow(),td=tr.insertCell();td.colSpan=10;td.textContent='No saved models available yet.';rows.clear();return}
  if(!rows.size)body.replaceChildren();
  const seen=new Set();let previous=null;
  for(const model of data.models){seen.add(model.id);let row=rows.get(model.id);
   if(!row){row=document.createElement('tr');for(let i=0;i<10;i++)row.insertCell();row.cells[3].className='test-state';const button=document.createElement('button');button.type='button';button.textContent='Test';button.setAttribute('aria-label','Test model '+model.version.slice(0,12));button.onclick=async()=>{button.disabled=true;try{await api('POST',{model_id:model.id,benchmark_id:benchmark.id});await refresh()}catch(e){notice(e.message,true)}finally{if(!['queued','running'].includes(row.dataset.state))button.disabled=false}};row.cells[9].append(button);rows.set(model.id,row);body.append(row)}
   if(row.previousElementSibling!==previous)body.insertBefore(row,previous?previous.nextSibling:body.firstChild);previous=row;
   const job=model.test,result=job?.state==='complete'&&job.benchmark_id===benchmark?.id?job.result:null;row.dataset.state=job?.state||'';
   const anomaly=result?.per_class?.anomalous;
   const status=job?.state==='failed'?'Failed: '+job.error:job?.state==='queued'?'Queued':job?.state==='running'?'Testing…':job?.state==='complete'?(result?'Complete':'Earlier sample · retest'):'Not tested';
   const values=[model.version.slice(0,12)+(model.active?' · Active':''),date(model.created_epoch),model.reviewed_frames?.toLocaleString()||'—',status,pct(result?.accuracy),result?`${result.correct} / ${result.total}`:'—',pct(anomaly?.precision),pct(anomaly?.recall),date(job?.finished_epoch)];
   values.forEach((value,i)=>{if(row.cells[i].textContent!==value)row.cells[i].textContent=value});row.cells[0].title=model.version;row.cells[9].firstChild.disabled=!benchmark||['queued','running'].includes(job?.state);
  }
  for(const [id,row]of rows)if(!seen.has(id)){row.remove();rows.delete(id)}
 }
 async function refresh(){if(busy)return;busy=true;try{render(await api());notice('')}catch(e){notice(e.name==='TimeoutError'?'Model tests are taking longer to respond. Retrying…':e.message,true)}finally{busy=false}}
 refresh();setInterval(refresh,3000);
})();
