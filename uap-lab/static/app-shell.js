'use strict';
(()=>{
 const titles={'/metrics':'Metrics','/label-videos':'Label videos','/tracks':'Labeled objects','/labels':'Labeled objects','/events':'Recent events','/training':'Hourly training','/email-review':'Review detection'};
 const root=location.pathname==='/';const old=document.querySelector('header.app-controls');
 const header=document.createElement('header');header.className='app-controls station-header';header.setAttribute('aria-label','Field Station');
 const button=document.getElementById('menuToggle')||document.createElement('button');button.id='menuToggle';button.className='station-menu-button';button.type='button';button.setAttribute('aria-label','Open navigation');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','mainNav');button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';
 const brand=document.createElement('a');brand.className='station-brand';brand.href='/';brand.textContent='Field Station';
 const title=document.createElement('span');title.className='station-page-title';title.textContent=titles[location.pathname]||({label:'Label videos',test:'Test model'}[new URLSearchParams(location.search).get('view')]||'Camera');
 const nav=document.getElementById('mainNav')||document.createElement('nav');nav.id='mainNav';nav.setAttribute('aria-label','Main navigation');nav.hidden=true;
 if(!root){for(const [name,url]of [['Camera','/'],['Label videos','/label-videos'],['Test model','/?view=test'],['Labeled objects','/tracks'],['Metrics','/metrics'],['Hourly training','/training']]){const a=document.createElement('a');a.href=url;a.textContent=name;if(url===location.pathname||(url==='/tracks'&&location.pathname==='/labels'))a.setAttribute('aria-current','page');nav.append(a);}}
 if(root){for(const name of ['Camera','Label videos','Test model','Labeled objects','Metrics','Hourly training']){const el=[...nav.children].find(e=>e.textContent===name);if(el)nav.append(el);}}
 header.append(button,brand,title,nav);
 for(const id of ['infoToggle','infoPanel']){const el=document.getElementById(id);if(el)header.append(el);}
 if(old)old.remove();document.body.prepend(header);document.body.classList.add('has-station-header');
 function close(focus=false){nav.hidden=true;button.setAttribute('aria-expanded','false');if(focus)button.focus();}
 if(!root){button.onclick=()=>{const open=nav.hidden;nav.hidden=!open;button.setAttribute('aria-expanded',String(open));if(open)nav.querySelector('a')?.focus();};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!nav.hidden)close(true);});}
 document.addEventListener('click',e=>{if(!header.contains(e.target))close();});
 nav.addEventListener('keydown',e=>{const links=[...nav.querySelectorAll('a,button')];if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;e.preventDefault();const i=links.indexOf(document.activeElement);links[e.key==='Home'?0:e.key==='End'?links.length-1:(i+(e.key==='ArrowUp'?-1:1)+links.length)%links.length]?.focus();});
 window.addEventListener('station-view',e=>{const mode=e.detail;title.textContent={live:'Camera',label:'Label videos',test:'Test model'}[mode]||'Camera';for(const [id,value]of [['liveTab','live'],['labelTab','label'],['testTab','test']]){const el=document.getElementById(id);if(mode===value)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');}const url=new URL(location.href);if(mode==='live')url.searchParams.delete('view');else url.searchParams.set('view',mode);history.replaceState(null,'',url);});
 if(location.pathname==='/training'){
  const main=document.createElement('main');main.className='station-training-page';for(const el of [...document.body.childNodes])if(el!==header&&!(el.nodeType===1&&['SCRIPT','STYLE','LINK'].includes(el.tagName)))main.append(el);document.body.append(main);
 }
})();
// Keep the current document and unsaved controls intact across service restarts.
(()=>{
 let instance=null,interrupted=false,failures=0,dialog=null,focus=null,connectionNotice=null;
 function show(title,message){
  if(!dialog){dialog=document.createElement('dialog');dialog.id='stationMaintenance';dialog.setAttribute('aria-labelledby','stationMaintenanceTitle');dialog.innerHTML='<div class="station-maintenance-brand">Field Station</div><div class="station-maintenance-content" role="status" aria-live="polite"><span class="station-spinner" aria-hidden="true"></span><h1 id="stationMaintenanceTitle"></h1><p id="stationMaintenanceMessage"></p><p class="maintenance-note">Leave this page open. Your current page will return when the station is ready.</p></div>';dialog.addEventListener('cancel',e=>e.preventDefault());document.body.append(dialog);}
  dialog.querySelector('h1').textContent=title;dialog.querySelector('#stationMaintenanceMessage').textContent=message;
  if(!dialog.open){focus=document.activeElement;dialog.showModal();}
 }
 function connectionWarning(visible){
  if(!connectionNotice){connectionNotice=document.createElement('div');connectionNotice.className='station-training-notice';connectionNotice.id='stationConnectionNotice';connectionNotice.setAttribute('role','status');connectionNotice.textContent='Connection is slow. Waiting for the station; pending saves are not yet confirmed.';document.body.append(connectionNotice);}
  connectionNotice.hidden=!visible;
 }
 async function poll(){
  try{
   const response=await fetch('/api/service-status',{cache:'no-store',priority:'high',signal:AbortSignal.timeout(8000)});
   if(!response.ok)throw Error('Unavailable');const state=await response.json();failures=0;connectionWarning(false);
   if(!state.available){interrupted=true;show(state.title,state.message);}
   else{
    if(interrupted||(instance&&instance!==state.instance)){
     const r=await fetch('/api/labeled-frames/token',{cache:'no-store',priority:'high',signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error('Not ready');const auth=await r.json();
     window.dispatchEvent(new CustomEvent('station-reconnected',{detail:{token:auth.token}}));
     if(dialog?.open){dialog.close();focus?.focus();}interrupted=false;
    }
    instance=state.instance;
   }
  }catch{if(++failures>=2)connectionWarning(true);}
  setTimeout(poll,2500);
 }
 poll();
})();

// Manual requests share the scheduled trainer and its model validation gates.
(()=>{
 if(location.pathname!=='/label-videos')return;
 const button=document.createElement('button');button.type='button';button.id='trainNow';button.className='station-train-button';button.textContent='Train now';button.disabled=true;
 document.querySelector('.station-header').append(button);
 const notice=document.createElement('div');notice.className='station-training-notice';notice.setAttribute('role','status');notice.hidden=true;document.body.append(notice);
 let submitting=false,watching=false;
 const labels={queued:'Queued…',starting:'Starting…',snapshot:'Preparing…',building:'Preparing…',training:'Training…',refining_class_corrections:'Refining…',evaluating:'Validating…',activating:'Deploying…'};
 const messages={waiting_for_data:'More reviewed examples are needed before training can finish.',refining_class_corrections:'Checking class corrections.',queued:'Training queued. The trainer checks for requests every minute.',starting:'Training is starting.',snapshot:'Collecting human-reviewed labels.',building:'Preparing the training dataset.',training:'Training a model with your labels.',evaluating:'Checking the candidate model before release.',activating:'Deploying the validated model.',deployed:'The new model is live.',validated_unchanged:'Training validated. The active model already uses these labels.',rejected:'The candidate did not pass validation. The current model remains active.',superseded:'Labels changed during training. A fresh run is needed.',error:'Training could not finish. See Hourly training for details.',rolled_back:'The candidate was rolled back. The previous model remains active.'};
 function render(state){button.disabled=submitting||state.busy;button.textContent=state.busy?(labels[state.phase]||'Training…'):'Train now';if(watching){notice.hidden=false;notice.textContent=messages[state.phase]||(state.busy?'Training is running.':'Training finished. See Hourly training for details.');}}
 async function poll(){try{const r=await fetch('/api/training-control',{cache:'no-store'});if(!r.ok)throw Error();render(await r.json());}catch{button.disabled=true;button.textContent='Train now';button.title='Waiting for the training service';}}
 button.onclick=async()=>{if(button.disabled)return;submitting=true;button.disabled=true;button.textContent='Queuing…';watching=true;try{const auth=await fetch('/api/labeled-frames/token',{cache:'no-store'});if(!auth.ok)throw Error();const {token}=await auth.json();const r=await fetch('/api/training-control/start',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:'{}'});if(!r.ok)throw Error();submitting=false;render(await r.json());}catch{submitting=false;notice.hidden=false;notice.textContent='Could not confirm the training request. Checking its status…';await poll();}};
 window.addEventListener('station-reconnected',poll);poll();setInterval(poll,5000);
})();
