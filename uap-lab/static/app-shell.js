'use strict';
(()=>{
 const titles={'/label-videos':'Label videos','/tracks':'Labeled objects','/labels':'Labeled objects','/events':'Recent events','/training':'Hourly training','/email-review':'Review detection'};
 const root=location.pathname==='/';const old=document.querySelector('header.app-controls');
 const header=document.createElement('header');header.className='app-controls station-header';header.setAttribute('aria-label','Field Station');
 const button=document.getElementById('menuToggle')||document.createElement('button');button.id='menuToggle';button.className='station-menu-button';button.type='button';button.setAttribute('aria-label','Open navigation');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','mainNav');button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';
 const brand=document.createElement('a');brand.className='station-brand';brand.href='/';brand.textContent='Field Station';
 const title=document.createElement('span');title.className='station-page-title';title.textContent=titles[location.pathname]||({label:'Label videos',test:'Test model'}[new URLSearchParams(location.search).get('view')]||'Observatory');
 const nav=document.getElementById('mainNav')||document.createElement('nav');nav.id='mainNav';nav.setAttribute('aria-label','Main navigation');nav.hidden=true;
 if(!root){for(const [name,url]of [['Observatory','/'],['Label videos','/label-videos'],['Test model','/?view=test'],['Labeled objects','/tracks'],['Recent events','/events'],['Hourly training','/training']]){const a=document.createElement('a');a.href=url;a.textContent=name;if(url===location.pathname||(url==='/tracks'&&location.pathname==='/labels'))a.setAttribute('aria-current','page');nav.append(a);}}
 if(root){for(const name of ['Observatory','Label videos','Test model','Labeled objects','Recent events','Hourly training']){const el=[...nav.children].find(e=>e.textContent===name);if(el)nav.append(el);}}
 header.append(button,brand,title,nav);
 for(const id of ['infoToggle','infoPanel']){const el=document.getElementById(id);if(el)header.append(el);}
 if(old)old.remove();document.body.prepend(header);document.body.classList.add('has-station-header');
 function close(focus=false){nav.hidden=true;button.setAttribute('aria-expanded','false');if(focus)button.focus();}
 if(!root){button.onclick=()=>{const open=nav.hidden;nav.hidden=!open;button.setAttribute('aria-expanded',String(open));if(open)nav.querySelector('a')?.focus();};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!nav.hidden)close(true);});}
 document.addEventListener('click',e=>{if(!header.contains(e.target))close();});
 nav.addEventListener('keydown',e=>{const links=[...nav.querySelectorAll('a,button')];if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;e.preventDefault();const i=links.indexOf(document.activeElement);links[e.key==='Home'?0:e.key==='End'?links.length-1:(i+(e.key==='ArrowUp'?-1:1)+links.length)%links.length]?.focus();});
 window.addEventListener('station-view',e=>{const mode=e.detail;title.textContent={live:'Observatory',label:'Label videos',test:'Test model'}[mode]||'Observatory';for(const [id,value]of [['liveTab','live'],['labelTab','label'],['testTab','test']]){const el=document.getElementById(id);if(mode===value)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');}const url=new URL(location.href);if(mode==='live')url.searchParams.delete('view');else url.searchParams.set('view',mode);history.replaceState(null,'',url);});
 if(location.pathname==='/training'){
  const main=document.createElement('main');main.className='station-training-page';for(const el of [...document.body.childNodes])if(el!==header&&!(el.nodeType===1&&['SCRIPT','STYLE','LINK'].includes(el.tagName)))main.append(el);document.body.append(main);
 }
})();
// Keep the current document and unsaved controls intact across service restarts.
(()=>{
 let instance=null,interrupted=false,failures=0,dialog=null,focus=null;
 function show(title,message){
  if(!dialog){dialog=document.createElement('dialog');dialog.id='stationMaintenance';dialog.setAttribute('aria-labelledby','stationMaintenanceTitle');dialog.innerHTML='<div class="station-maintenance-brand">Field Station</div><div class="station-maintenance-content" role="status" aria-live="polite"><span class="station-spinner" aria-hidden="true"></span><h1 id="stationMaintenanceTitle"></h1><p id="stationMaintenanceMessage"></p><p class="maintenance-note">Leave this page open. Your current page will return when the station is ready.</p></div>';dialog.addEventListener('cancel',e=>e.preventDefault());document.body.append(dialog);}
  dialog.querySelector('h1').textContent=title;dialog.querySelector('#stationMaintenanceMessage').textContent=message;
  if(!dialog.open){focus=document.activeElement;dialog.showModal();}
 }
 async function poll(){
  try{
   const response=await fetch('/api/service-status',{cache:'no-store',signal:AbortSignal.timeout(4000)});
   if(!response.ok)throw Error('Unavailable');const state=await response.json();failures=0;
   if(!state.available){interrupted=true;show(state.title,state.message);}
   else{
    if(interrupted||(instance&&instance!==state.instance)){
     const r=await fetch('/api/labeled-frames/token',{cache:'no-store',signal:AbortSignal.timeout(4000)});if(!r.ok)throw Error('Not ready');const auth=await r.json();
     window.dispatchEvent(new CustomEvent('station-reconnected',{detail:{token:auth.token}}));
     if(dialog?.open){dialog.close();focus?.focus();}interrupted=false;
    }
    instance=state.instance;
   }
  }catch{if(++failures>=2){interrupted=true;show('Reconnecting to Field Station','The station connection is temporarily unavailable. We’re checking for it automatically.');}}
  setTimeout(poll,2500);
 }
 poll();
})();
