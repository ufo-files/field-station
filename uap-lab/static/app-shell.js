'use strict';
(()=>{
 const titles={'/models':'Models','/test-model':'Test model','/metrics':'Metrics','/label-videos':'Review detections','/tracks':'Labeled objects','/labels':'Labeled objects','/events':'Recent events','/training':'Training history','/email-review':'Review detection'};
 const root=location.pathname==='/';const old=document.querySelector('header.app-controls');
 const header=document.createElement('header');header.className='app-controls station-header';header.setAttribute('aria-label','Field Station');
 const button=document.getElementById('menuToggle')||document.createElement('button');button.id='menuToggle';button.className='station-menu-button';button.type='button';button.setAttribute('aria-label','Open navigation');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','mainNav');button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';
 const brand=document.createElement('a');brand.className='station-brand';brand.href='/';brand.textContent='Field Station';
 const modelHash=document.createElement('small');modelHash.className='station-model-hash';modelHash.textContent='Model unavailable';brand.append(modelHash);
 async function refreshModelHash(){if(document.hidden)return;try{const r=await fetch('/api/live/status',{cache:'no-store',signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error();const data=await r.json(),hash=data.active_model_hash;modelHash.textContent=hash?hash.slice(0,12):'Model unavailable';modelHash.title=hash||'Active runtime not confirmed';}catch{modelHash.textContent='Model unavailable';}}
 refreshModelHash();setInterval(refreshModelHash,10000);
 const title=document.createElement('span');title.className='station-page-title';title.textContent=titles[location.pathname]||({label:'Review detections',test:'Test model'}[new URLSearchParams(location.search).get('view')]||'Live stream');
 const nav=document.getElementById('mainNav')||document.createElement('nav');nav.id='mainNav';nav.setAttribute('aria-label','Main navigation');nav.hidden=true;
 if(!root){for(const [name,url]of [['Live stream','/'],['Review detections','/label-videos'],['Models','/models']]){const a=document.createElement('a');a.href=url;a.textContent=name;if(url===location.pathname||(url==='/tracks'&&location.pathname==='/labels'))a.setAttribute('aria-current','page');nav.append(a);}}
 if(root){const modelButton=document.getElementById('testTab');if(modelButton){modelButton.textContent='Models';modelButton.onclick=()=>{location.href='/models'};}for(const oldLink of nav.querySelectorAll('a[href="/metrics"],a[href="/training"]'))oldLink.remove();}
 if(root){for(const name of ['Live stream','Review detections','Models']){const el=[...nav.children].find(e=>e.textContent===name);if(el)nav.append(el);}}
 header.append(button,brand,title,nav);
 for(const id of ['infoToggle','infoPanel']){const el=document.getElementById(id);if(el)header.append(el);}
 if(old)old.remove();document.body.prepend(header);document.body.classList.add('has-station-header');
 function close(focus=false){nav.hidden=true;button.setAttribute('aria-expanded','false');if(focus)button.focus();}
 if(!root){button.onclick=()=>{const open=nav.hidden;nav.hidden=!open;button.setAttribute('aria-expanded',String(open));if(open)nav.querySelector('a')?.focus();};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!nav.hidden)close(true);});}
 document.addEventListener('click',e=>{if(!header.contains(e.target))close();});
 nav.addEventListener('keydown',e=>{const links=[...nav.querySelectorAll('a,button')];if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;e.preventDefault();const i=links.indexOf(document.activeElement);links[e.key==='Home'?0:e.key==='End'?links.length-1:(i+(e.key==='ArrowUp'?-1:1)+links.length)%links.length]?.focus();});
 window.addEventListener('station-view',e=>{const mode=e.detail;title.textContent={live:'Live stream',label:'Review detections',test:'Test model'}[mode]||'Live stream';for(const [id,value]of [['liveTab','live'],['labelTab','label'],['testTab','test']]){const el=document.getElementById(id);if(mode===value)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');}const url=new URL(location.href);if(mode==='live')url.searchParams.delete('view');else url.searchParams.set('view',mode);history.replaceState(null,'',url);});
 if(location.pathname==='/training'&&!document.querySelector('main.training-history')){
  const main=document.createElement('main');main.className='station-training-page';for(const el of [...document.body.childNodes])if(el!==header&&!(el.nodeType===1&&['SCRIPT','STYLE','LINK'].includes(el.tagName)))main.append(el);document.body.append(main);
 }
})();
// One notification region for connection, review, and training messages.
(()=>{
 const region=document.createElement('div');region.id='stationNotifications';region.setAttribute('aria-label','Notifications');document.body.append(region);
 function mount(node){node.classList.add('station-notification');region.append(node);return node;}
 function set(key,text,error=false){let node=document.getElementById(key);if(!node){node=document.createElement('div');node.id=key;node.setAttribute('role','status');mount(node);}node.textContent=text;node.classList.toggle('error',error);node.hidden=!text;return node;}
 function clear(key){const node=document.getElementById(key);if(node)node.hidden=true;}
 window.stationNotifications={mount,set,clear};
 for(const id of ['notice','queueToast']){const node=document.getElementById(id);if(node)mount(node);}
 const prior=document.getElementById('notice');if(prior?.textContent.startsWith('Connection')){set('stationConnectionNotice','Connection is slow. Waiting for the station…',true);prior.textContent='';}
})();
// Keep the current document and unsaved controls intact across service restarts.
(()=>{
 let instance=null,interrupted=false,failures=0,dialog=null,focus=null;
 function show(title,message){
  if(!dialog){dialog=document.createElement('dialog');dialog.id='stationMaintenance';dialog.setAttribute('aria-labelledby','stationMaintenanceTitle');dialog.innerHTML="<div class=\"station-test-card\"><div class=\"test-grid\" aria-hidden=\"true\"></div>\n<div class=\"test-bars test-bars-top\" aria-hidden=\"true\"></div><div class=\"test-bars test-bars-bottom\" aria-hidden=\"true\"></div>\n<div class=\"test-ring\" aria-hidden=\"true\"><span class=\"test-cross test-cross-h\"></span><span class=\"test-cross test-cross-v\"></span></div>\n<div class=\"test-message\"><div class=\"test-portrait\" aria-hidden=\"true\"><img class=\"test-emblem\" fetchpriority=\"high\" src=\"/ufo-engraving.png?v=original-restored-10\" alt=\"\"></div><strong id=\"stationMaintenanceTitle\" role=\"heading\" aria-level=\"1\">WE'LL BE RIGHT BACK</strong><span class=\"test-standby maintenance-description\" id=\"stationMaintenanceMessage\">Checking station status\u2026</span></div>\n<svg class=\"test-grain\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\"><defs><filter id=\"maintenance-grain\"><feTurbulence type=\"fractalNoise\" baseFrequency=\".8\" numOctaves=\"1\" stitchTiles=\"stitch\"/><feColorMatrix type=\"saturate\" values=\"0\"/><feComponentTransfer><feFuncA type=\"linear\" slope=\"0\" intercept=\"1\"/></feComponentTransfer></filter></defs><rect width=\"100%\" height=\"100%\" filter=\"url(#maintenance-grain)\"/></svg></div>";dialog.addEventListener('cancel',e=>e.preventDefault());document.body.append(dialog);}
  dialog.querySelector('#stationMaintenanceTitle').textContent=title==='Cleanup in progress'?'CLEANUP IN PROGRESS':"WE'LL BE RIGHT BACK";dialog.querySelector('#stationMaintenanceMessage').textContent=message;
  if(!dialog.open){focus=document.activeElement;dialog.showModal();}
 }
 function connectionWarning(visible){
  if(visible)window.stationNotifications.set('stationConnectionNotice','Connection is slow. Waiting for the station…',true);
  else window.stationNotifications.clear('stationConnectionNotice');
 }

 async function poll(){
  try{
   const response=await fetch('/api/service-status',{cache:'no-store',priority:'high',signal:AbortSignal.timeout(window.FIELD_PUBLIC_READ_ONLY===true?45000:8000)});
   if(!response.ok)throw Error('Unavailable');const state=await response.json();failures=0;connectionWarning(false);
   if(!state.available){interrupted=true;show(state.title,state.message);}
   else{
    if(interrupted||(instance&&instance!==state.instance)){
     const r=await fetch('/api/labeled-frames/token',{cache:'no-store',priority:'high',signal:AbortSignal.timeout(window.FIELD_PUBLIC_READ_ONLY===true?45000:8000)});if(!r.ok)throw Error('Not ready');const auth=await r.json();
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
 if(!['/label-videos','/models'].includes(location.pathname)||window.FIELD_PUBLIC_READ_ONLY===true)return;
 const button=document.createElement('button');button.type='button';button.id='trainNow';button.className='station-train-button';button.textContent='Train now';button.disabled=true;
 document.querySelector('.station-header').append(button);
 const notice=document.createElement('div');notice.className='station-training-notice';notice.setAttribute('role','status');notice.hidden=true;window.stationNotifications.mount(notice);
 let submitting=false,watching=false;
 const labels={queued:'Queued…',starting:'Starting…',snapshot:'Preparing…',building:'Preparing…',training:'Training…',refining_class_corrections:'Refining…',evaluating:'Validating…',activating:'Deploying…'};
 const messages={waiting_for_data:'Training could not start because independent training or validation data is missing.',not_promoted:'Training finished. The earlier model was kept because this run did not meet its release checks. Your labels are saved.',validated_no_improvement:'Training finished without a validated improvement. Your labels are saved and the current model remains active.',refining_class_corrections:'Checking class corrections.',queued:'Training queued. The trainer checks for requests every minute.',starting:'Training is starting.',snapshot:'Collecting human-reviewed labels.',building:'Preparing the training dataset.',training:'Training a model with your labels.',evaluating:'Checking the new model before release.',activating:'Deploying the validated model.',deployed:'The new model is live.',validated_unchanged:'Training validated. The active model already uses these labels.',rejected:'The new model did not pass validation. The current model remains active.',superseded:'Labels changed during training. A fresh run is needed.',error:'Training could not finish. See Models for details.',rolled_back:'The new model was rolled back. The previous model remains active.'};
 function render(state){button.disabled=submitting||state.busy;button.textContent=state.busy?(labels[state.phase]||'Training…'):'Train now';if(watching){notice.hidden=false;notice.textContent=(state.phase==='building'&&state.reason?state.reason:messages[state.phase])||(state.busy?'Training is running.':'Training finished. See Models for details.');}}
 async function poll(){try{const r=await fetch('/api/training-control',{cache:'no-store'});if(!r.ok)throw Error();render(await r.json());}catch{button.disabled=true;button.textContent='Train now';button.title='Waiting for the training service';}}
 button.onclick=async()=>{if(button.disabled)return;submitting=true;button.disabled=true;button.textContent='Queuing…';watching=true;try{const auth=await fetch('/api/labeled-frames/token',{cache:'no-store'});if(!auth.ok)throw Error();const {token}=await auth.json();const r=await fetch('/api/training-control/start',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:'{}'});if(!r.ok)throw Error();submitting=false;render(await r.json());}catch{submitting=false;notice.hidden=false;notice.textContent='Could not confirm the training request. Checking its status…';await poll();}};
 window.addEventListener('station-reconnected',poll);poll();setInterval(poll,5000);
})();

// Clear analysis and review backlogs from Review detections only.
(()=>{
 if(location.pathname!=='/label-videos'||window.FIELD_PUBLIC_READ_ONLY===true)return;
 const button=document.createElement('button');button.id='clearBacklog';button.type='button';button.className='station-train-button';button.textContent='Clear backlog';button.title='Skip queued analysis to live and dismiss pending reviews. Saved clips and labels are preserved.';
 document.querySelector('.station-header').append(button);
 const style=document.createElement('style');style.textContent='.station-header #clearBacklog{margin-left:0;white-space:nowrap}.station-header:has(#clearBacklog) #trainNow{margin-left:auto}@media(max-width:600px){.station-header:has(#clearBacklog) .station-page-title{display:none}.station-header:has(#trainNow):has(#clearBacklog) .station-brand{display:none}}';document.head.append(style);
 let watching=false,submitting=false,lastCompleted=null;
 function render(state){if(state.phase==='complete'&&state.request_id!==lastCompleted){lastCompleted=state.request_id;window.dispatchEvent(new CustomEvent('station-backlog-cleared'));}button.disabled=submitting||!!state.busy;button.textContent=state.busy?'Clearing…':'Clear backlog';if(!watching)return;
  let message='Clearing both backlogs…';
  if(state.phase==='complete'){const review=state.review||{};message=`Cleared ${(review.frames_cleared||0).toLocaleString()} unreviewed detections and ${(review.videos_cleared||0).toLocaleString()} videos. Deleted ${(review.media_files_deleted||0).toLocaleString()} media files (${((review.media_bytes_deleted||0)/1024**3).toFixed(2)} GiB). Human-reviewed evidence kept.${review.media_deferred?' Some active items are awaiting media cleanup.':''}`;if(state.analysis?.skipped==='generation_transition')message+=' Capture changed during cleanup; analysis will follow the new capture.';window.dispatchEvent(new CustomEvent('station-backlog-cleared'));watching=false;}
  if(state.phase==='error'){message='Backlog cleanup could not finish: '+state.error;watching=false;}
  window.stationNotifications.set('backlogNotice',message,state.phase==='error');
 }
 async function poll(){try{const r=await fetch('/api/backlog',{cache:'no-store',signal:AbortSignal.timeout(8000)});if(r.ok)render(await r.json());}catch{}}
 button.onclick=async()=>{if(button.disabled)return;submitting=true;watching=true;button.disabled=true;button.textContent='Clearing…';window.stationNotifications.set('backlogNotice','Clearing both backlogs…');try{const a=await fetch('/api/labeled-frames/token',{cache:'no-store'});if(!a.ok)throw Error('Station unavailable');const {token}=await a.json();const r=await fetch('/api/backlog/clear',{method:'POST',headers:{'X-Lab-Token':token,'Content-Type':'application/json'},body:'{}'});if(!r.ok)throw Error('Request failed');submitting=false;render(await r.json());}catch{ submitting=false;window.stationNotifications.set('backlogNotice','Checking whether the backlog cleanup started…');await poll();}};
 window.addEventListener('station-reconnected',poll);poll();setInterval(poll,3000);
})();

// Operator capture control is available only on the private review screen.
(()=>{
 if(location.pathname!=='/label-videos'||window.FIELD_PUBLIC_READ_ONLY===true)return;
 const header=document.querySelector('.station-header');if(!header)return;
 const button=document.createElement('button');button.id='pauseCapture';button.type='button';button.className='station-train-button';button.style.marginLeft='0';button.style.whiteSpace='nowrap';button.textContent='Pause capture';button.disabled=true;
 header.insertBefore(button,document.getElementById('clearBacklog'));
 let paused=false,busy=false;
 function render(value,pending=false){paused=value;button.textContent=pending?(paused?'Pausing…':'Resuming…'):(paused?'Resume capture':'Pause capture');button.setAttribute('aria-pressed',String(paused));button.disabled=busy||pending;}
 async function poll(){if(busy)return;try{const r=await fetch('/api/live/capture',{cache:'no-store',signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error();const state=await r.json();render(state.capture_paused===true,state.pending===true);}catch{button.disabled=true;button.title='Waiting for capture status';}}
 button.onclick=async()=>{if(busy)return;busy=true;button.disabled=true;try{
  const auth=await fetch('/api/labeled-frames/token',{cache:'no-store'});if(!auth.ok)throw Error('Station unavailable');const {token}=await auth.json();
  const response=await fetch('/api/live/pause',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify({paused:!paused}),signal:AbortSignal.timeout(65000)});const result=await response.json();if(!response.ok)throw Error(result.error||'Capture control failed');render(result.paused,result.pending);
  window.stationNotifications.set('capturePauseNotice',result.pending?'Capture change requested. Waiting for the capture worker.':(result.paused?'Capture paused. Live preview stays on.':'Capture resumed.'));
 }catch(e){window.stationNotifications.set('capturePauseNotice',e.message,true);}finally{busy=false;await poll();}};
 poll();setInterval(poll,5000);window.addEventListener('station-reconnected',poll);
})();

// A lightweight arrival hint; never fetch the object library just to show a dot.
(()=>{
 if(window.FIELD_PUBLIC_READ_ONLY===true||!['/','/models','/label-videos','/email-review'].includes(location.pathname))return;
 const button=document.getElementById('menuToggle');if(!button)return;
 const dot=document.createElement('span');dot.className='station-detection-dot';dot.hidden=true;dot.setAttribute('aria-hidden','true');button.append(dot);
 const reviewLink=document.querySelector('#mainNav a[href="/label-videos"]')||document.getElementById('labelTab');
 const reviewDot=document.createElement('span');reviewDot.className='station-review-dot';reviewDot.hidden=true;reviewDot.setAttribute('aria-hidden','true');reviewLink?.append(reviewDot);
 const key='field-station.detections-seen';let latest=null,seen=null,busy=false;
 let reviewing=['/label-videos','/email-review'].includes(location.pathname)||(location.pathname==='/'&&new URLSearchParams(location.search).get('view')==='label');
 try{seen=JSON.parse(localStorage.getItem(key));}catch{}
 function render(){const unread=!reviewing&&latest?.id&&seen&&latest.epoch>seen.epoch;dot.hidden=!unread;reviewDot.hidden=!unread;reviewLink?.setAttribute('aria-label',unread?'Review detections — new detections':'Review detections');button.setAttribute('aria-label',unread?'Open navigation — new detections':'Open navigation');}
 function acknowledge(){if(latest){seen=latest;try{localStorage.setItem(key,JSON.stringify(seen));}catch{}}render();}
 async function poll(){if(busy||document.hidden)return;busy=true;try{
  const r=await fetch('/api/detections/latest',{cache:'no-store',signal:AbortSignal.timeout(5000)});if(!r.ok)return;
  const value=await r.json();latest=typeof value.id==='string'&&Number.isFinite(value.epoch)?value:{id:null,epoch:0};
  if(!seen||reviewing)acknowledge();else render();
 }catch{}finally{busy=false;}}
 window.addEventListener('station-view',e=>{reviewing=e.detail==='label';if(reviewing)acknowledge();else render();void poll();});
 window.addEventListener('storage',e=>{if(e.key===key){try{seen=JSON.parse(e.newValue);}catch{}render();}});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)void poll();});
 window.addEventListener('station-reconnected',poll);void poll();setInterval(poll,5000);
})();

// Small live preview on the review and model workspaces; one request at a time.
(()=>{
 if(!['/label-videos','/models'].includes(location.pathname))return;
 const pip=document.createElement('a');pip.id='stationLivePip';pip.href='/';pip.setAttribute('aria-label','Open Live stream');
 const image=document.createElement('img');image.alt='Live camera preview';image.hidden=true;
 const label=document.createElement('span');label.className='pip-label';label.textContent='Live stream ↗';
 const status=document.createElement('span');status.className='pip-status';status.setAttribute('role','status');status.textContent='Connecting…';
 const badge=document.createElement('span');badge.className='pip-badge';badge.textContent='Connecting';badge.setAttribute('role','status');pip.append(image,label,status,badge);document.body.append(pip);
 let busy=false,timer=null,controller=null,currentUrl=null,stopped=false,frameAt=0,session=null,sessionAt=0,signal=null,signalAt=0,stateBusy=false,stateTimer=null;
 function renderBadge(){let text='Connecting',state='connecting';if(signal?.camera_no_signal===true&&Date.now()-signalAt<7000){text='No signal';state='no-signal';}else if(frameAt&&Date.now()-frameAt<5000){if(session?.active?.state==='recording'&&Date.now()-sessionAt<7000&&!session.capture_paused&&!session.recording_paused){text='Recording';state='recording';}else{text='Live';state='live';}}badge.textContent=text;badge.dataset.state=state;}
 async function pollState(){if(stopped||stateBusy||document.hidden)return;stateBusy=true;try{await Promise.allSettled([['/api/live/session',v=>{session=v;sessionAt=Date.now();}],['/api/live/status',v=>{signal=v;signalAt=Date.now();}]].map(async([path,save])=>{const r=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(5000)});if(r.ok)save(await r.json());}));}finally{stateBusy=false;renderBadge();if(!stopped&&!document.hidden)stateTimer=setTimeout(pollState,3000);}}
 async function frame(){
  if(stopped||busy||document.hidden)return;busy=true;let failed=false,nextUrl=null;
  controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),8000);
  try{
   const response=await fetch('/api/live/frame?t='+Date.now(),{cache:'no-store',signal:controller.signal});
   if(!response.ok)throw Error('Camera unavailable');
   nextUrl=URL.createObjectURL(await response.blob());const decoded=new Image();decoded.src=nextUrl;await decoded.decode();
   if(stopped||document.hidden)return;
   const previous=currentUrl;currentUrl=nextUrl;nextUrl=null;image.src=currentUrl;image.hidden=false;status.hidden=true;frameAt=Date.now();renderBadge();if(previous)URL.revokeObjectURL(previous);
  }catch{if(!stopped&&!document.hidden){failed=true;frameAt=0;renderBadge();image.hidden=true;status.textContent='Camera unavailable';status.hidden=false;}}
  finally{clearTimeout(timeout);if(nextUrl)URL.revokeObjectURL(nextUrl);busy=false;controller=null;if(!stopped&&!document.hidden)timer=setTimeout(frame,failed?2000:500);}
 }
 document.addEventListener('visibilitychange',()=>{clearTimeout(timer);clearTimeout(stateTimer);if(document.hidden)controller?.abort();else{void frame();void pollState();}});
 window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);clearTimeout(stateTimer);controller?.abort();if(currentUrl)URL.revokeObjectURL(currentUrl);});
 window.addEventListener('pageshow',()=>{if(stopped){stopped=false;void frame();void pollState();}});
 void frame();void pollState();
})();
