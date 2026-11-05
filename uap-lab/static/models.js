'use strict';
(()=>{
 const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg',sources={metrics:{},history:{},catalog:{}},loading=new Set(),loaded=new Set(),failures=new Map(),nodes=new Map();let rows=[],selected=null,posting=new Set();
 const readOnly=window.FIELD_PUBLIC_READ_ONLY===true;
 if(readOnly)$('modelsTable').tHead.rows[0].cells[10].hidden=true;
 const percent=v=>typeof v==='number'&&Number.isFinite(v)?(100*v).toFixed(1)+'%':'—';
 const date=t=>t?new Date(t*1000).toLocaleString():'—';
 const count=v=>v==null?'—':Number(v).toLocaleString();
 const notify=(message,error=false)=>window.stationNotifications?.set('modelDashboardNotice',message,error);
 function select(key,scroll=false){selected=key;const row=rows.find(r=>r.key===key);if(!row)return;for(const [k,n]of nodes)n.classList.toggle('selected',k===key);for(const dot of $('modelGraph').querySelectorAll('.point'))dot.classList.toggle('selected',dot.dataset.key===key);$('graphSelection').textContent=`${date(row.epoch)} · ${row.status} · Run ${percent(row.runAccuracy)} · Previous ${percent(row.baselineAccuracy)} · Latest test ${percent(row.testAccuracy)}${row.reason?' · '+row.reason:''}`;if(scroll)nodes.get(key)?.scrollIntoView({block:'nearest',behavior:'smooth'});}
 function svg(tag,attrs,text){const n=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;$('modelGraph').append(n);return n;}
 function draw(){
  const chart=$('modelGraph');chart.replaceChildren();const points=[...rows].filter(r=>r.epoch).reverse(),measure=$('modelMeasure').value;let measured=0;
  const width=Math.max(320,chart.clientWidth),height=Math.max(90,chart.clientHeight);chart.setAttribute('viewBox',`0 0 ${width} ${height}`);
  const start=points[0]?.epoch||0,end=points.at(-1)?.epoch||1,x=t=>46+(start===end ? .5 : (t-start)/(end-start))*(width-60),y=v=>height-25-Math.max(0,Math.min(1,v))*(height-40);
  for(let n=0;n<=100;n+=25){svg('line',{x1:46,x2:width-14,y1:y(n/100),y2:y(n/100),class:'grid'});svg('text',{x:39,y:y(n/100)+4,'text-anchor':'end'},n+'%');}
  if(points.length){svg('text',{x:46,y:height-4},new Date(start*1000).toLocaleDateString());svg('text',{x:width-14,y:height-4,'text-anchor':'end'},new Date(end*1000).toLocaleDateString());}
  for(const [series,css]of [['baseline','baseline'],['candidate','candidate'],['test','test']]){
   let group=[];
   function flush(){
    if(group.length>1){
     let d=`M ${x(group[0].row.epoch)} ${y(group[0].value)}`;
     for(let i=1;i<group.length;i++){const a=group[i-1],b=group[i],mid=(x(a.row.epoch)+x(b.row.epoch))/2;d+=` C ${mid} ${y(a.value)}, ${mid} ${y(b.value)}, ${x(b.row.epoch)} ${y(b.value)}`;}
     const line=svg('path',{d,class:`trend ${css}`,'stroke-linecap':'round','stroke-linejoin':'round'});
     const label={baseline:'Previous model',candidate:'Current model',test:'Test model'}[series];line.append(Object.assign(document.createElementNS(NS,'title'),{textContent:label}));
     const samples=[...group];line.style.cursor='pointer';line.onclick=e=>{const px=(e.clientX-chart.getBoundingClientRect().left)*width/chart.getBoundingClientRect().width;select(samples.reduce((a,b)=>Math.abs(x(a.row.epoch)-px)<Math.abs(x(b.row.epoch)-px)?a:b).row.key,true);};
    }
    group=[];
   }
   for(const row of points){const value=ModelDashboardData.score(row,series,measure);if(value===null){flush();continue;}measured++;group.push({row,value});}
   flush();
  }
  $('graphEmpty').hidden=measured>0;
 }
 async function test(key){if(readOnly)return;const row=rows.find(r=>r.key===key),model=row?.model,benchmark=sources.catalog.benchmark;if(!model||!benchmark||posting.has(model.id))return;posting.add(model.id);render();try{const r=await fetch('/api/model-tests',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':sources.catalog.token},body:JSON.stringify({model_id:model.id,benchmark_id:benchmark.id}),signal:AbortSignal.timeout(15000)});const value=await r.json();if(!r.ok)throw Error(value.error||'Test could not start');notify('Model test queued.');await load('catalog');}catch(e){notify(e.message,true)}finally{posting.delete(model.id);render();}}
 function render(){
  rows=ModelDashboardData.merge(sources.metrics,sources.history,sources.catalog);const body=$('unifiedModelRows');if(!nodes.size)body.replaceChildren();const seen=new Set();let previous=null;
  for(const row of rows){seen.add(row.key);let tr=nodes.get(row.key);
   if(!tr){tr=document.createElement('tr');tr.dataset.key=row.key;tr.tabIndex=0;for(let i=0;i<11;i++)tr.insertCell();tr.cells[1].append(Object.assign(document.createElement('span'),{className:'model-id'}));const details=document.createElement('details');details.className='model-details';details.append(document.createElement('summary'),document.createElement('p'));tr.cells[2].append(details);const button=document.createElement('button');button.type='button';button.textContent='Test';button.onclick=e=>{e.stopPropagation();test(tr.dataset.key)};tr.cells[10].append(button);tr.onclick=e=>{if(!e.target.closest('button,summary,details'))select(tr.dataset.key)};tr.onkeydown=e=>{if(e.target===tr&&(e.key==='Enter'||e.key===' ')){e.preventDefault();select(tr.dataset.key)}};nodes.set(row.key,tr);body.append(tr);}
   if(tr.previousElementSibling!==previous)body.insertBefore(tr,previous?previous.nextSibling:body.firstChild);previous=tr;
   const metric=row.test||row.candidate,anomaly=metric?.per_class?.anomalous;const values={0:date(row.epoch),3:count(row.count),4:percent(row.runAccuracy),5:percent(row.baselineAccuracy),6:percent(row.testAccuracy),7:percent(anomaly?.precision),8:percent(anomaly?.recall),9:row.duration==null?'—':`${Math.floor(row.duration/60)}m ${Math.floor(row.duration%60)}s`};for(const [i,value]of Object.entries(values))if(tr.cells[i].textContent!==value)tr.cells[i].textContent=value;
   tr.cells[1].children[0].textContent=row.version?.slice(0,12)||row.point?.run_id||'Training run';tr.cells[1].children[0].title=row.version||'';
   let status=row.status;if(row.job?.state==='queued')status+=' · Test queued';if(row.job?.state==='running')status+=' · Testing';if(row.job?.state==='failed')status+=' · Test failed';
   const details=tr.cells[2].firstChild;details.firstChild.textContent=status;details.lastChild.textContent=[row.reason,row.job?.error,row.job?.state==='complete'&&!row.test?'Last test used an older sample; retest to compare.':'',row.test?`Latest test: ${row.test.correct} / ${row.test.total} correct · ${date(row.job.finished_epoch)}`:'',row.point?.evaluation_set?.kind==='random_training_sample'?'Run scores compare models on the same sampled training images.':''].filter(Boolean).join(' ')||'No additional details recorded.';
   tr.cells[7].title=tr.cells[8].title=row.test?'From the latest test on the current shared sample':'From this training run';const button=tr.cells[10].firstChild;tr.cells[10].hidden=readOnly;button.hidden=readOnly||!row.model;button.disabled=!sources.catalog.benchmark||posting.has(row.model?.id)||['queued','running'].includes(row.job?.state);button.textContent=row.job?.state==='running'?'Testing…':row.job?.state==='queued'?'Queued':'Test';button.setAttribute('aria-label','Test model '+(row.version?.slice(0,12)||''));
  }
  for(const [key,node]of nodes)if(!seen.has(key)){node.remove();nodes.delete(key)}
  if(!rows.length){const tr=body.insertRow();const td=tr.insertCell();td.colSpan=11;td.textContent=loaded.size?'No training runs or saved models yet.':'Loading models and training runs…';}
  const benchmark=sources.catalog.benchmark;$('modelBenchmark').textContent=benchmark?`${benchmark.count} training frames · Shared test sample ${benchmark.id.slice(0,8)}`:'Shared test sample pending';
  $('modelLoadStatus').textContent=failures.size?`Showing available data · Retrying ${[...failures.keys()].join(', ')}`:`${rows.length.toLocaleString()} entries${loading.size?' · Updating…':''}`;
  draw();if(selected)select(selected);
 }
 const endpoints={metrics:'/api/model-metrics',history:'/api/training-history',catalog:'/api/model-tests'};
 async function load(name){if(loading.has(name))return;loading.add(name);try{const r=await fetch(endpoints[name],{cache:'no-store',signal:AbortSignal.timeout(45000)});if(!r.ok)throw Error('Unavailable');sources[name]=await r.json();loaded.add(name);failures.delete(name);}catch(e){failures.set(name,e.message);}finally{loading.delete(name);render();}}
 function refresh(){if(document.hidden)return;for(const name of Object.keys(endpoints))load(name);}
 new ResizeObserver(()=>{draw();if(selected)select(selected)}).observe(document.querySelector('.graph-stage'));
 $('modelMeasure').onchange=()=>{draw();if(selected)select(selected)};window.addEventListener('station-reconnected',refresh);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});refresh();setInterval(refresh,30000);setInterval(()=>{if(!document.hidden&&rows.some(r=>['queued','running'].includes(r.job?.state)))load('catalog')},3000);
})();
