'use strict';
(()=>{
 const $=id=>document.getElementById(id),views=[['all','All'],['anomalous','Anomalous'],['not_anomalous','Not Anomalous'],['needs_review','Needs review'],['human_reviewed','Human-reviewed'],['human_reviewed_anomalous','Human-reviewed anomalous']];
 let view=new URLSearchParams(location.search).get('view')||'all',token='',cursor='',more=true,loading=false,version=0,anchor=null,draining=false;
 if(!views.some(([v])=>v===view))view='all';
 const rows=new Map(),selected=new Set(),pending=new Map(),deleting=new Set(),deletedIds=new Set(),prefix='field-station.object-review.';
 const pretty=label=>label==='anomalous'?'Anomalous':'Not Anomalous';
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 async function api(path,body){const r=await fetch(path,{signal:AbortSignal.timeout(30000),...(body?{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
 let noticeTimer;function notice(text){clearTimeout(noticeTimer);$('queueSaved').textContent=text;$('queueToast').hidden=false;noticeTimer=setTimeout(()=>{$('queueToast').hidden=true;},6000);}
 function matches(row){if(view==='human_reviewed_anomalous')return row.human_reviewed&&row.label==='anomalous';return view==='all'||(view==='needs_review'?!row.human_reviewed:view==='human_reviewed'?row.human_reviewed:row.label===view);}
 function selection(){
  const cards=new Map([...$('detectionQueue').children].map(n=>[n.dataset.id,n]));for(const [id,row] of rows){const card=cards.get(id);if(!card)continue;card.classList.toggle('selected',selected.has(id));card.querySelector('.frame-select').checked=selected.has(id);card.querySelectorAll('button,input').forEach(b=>b.disabled=pending.has(id)||deleting.has(id));}
  $('bulkReview').hidden=!selected.size;$('selectionCount').textContent=selected.size+' selected';
 }
 function select(id,event){if(pending.has(id)||deleting.has(id))return;const ids=[...rows.keys()],a=ids.indexOf(anchor),b=ids.indexOf(id);if(event.shiftKey&&a>=0){for(const k of ids.slice(Math.min(a,b),Math.max(a,b)+1))if(!pending.has(k))selected.add(k);}else{selected.has(id)?selected.delete(id):selected.add(id);anchor=id;}selection();}
 function card(row){
  const n=el('article');n.className='detection-card';n.dataset.id=row.id;
  const image=el('button');image.className='detection-image';image.type='button';image.setAttribute('aria-label','Select '+pretty(row.label)+' object');const img=el('img');img.src=row.image_url;img.alt=pretty(row.label)+' detected object';img.loading='lazy';image.append(img);image.onclick=e=>{select(row.id,e);n.classList.toggle('controls-open');};
  const badge=el('span',pretty(row.label)+' · '+(row.human_reviewed?'Human-reviewed':'Needs review'));badge.className='object-label';
  const actions=el('div');actions.className='category-actions';const grid=el('div');grid.className='category-grid';
  for(const label of ['anomalous','not_anomalous']){const b=el('button',pretty(label));b.type='button';b.setAttribute('aria-label','Label as '+pretty(label));b.onclick=()=>enqueue(row,label);grid.append(b);}
  const links=el('div');links.className='review-actions';const inspect=el('button','Inspect frame');inspect.onclick=()=>{$('queueFrameBox').hidden=true;$('queueFullFrame').onload=()=>{const b=row.frame_bounds,img=$('queueFullFrame'),box=$('queueFrameBox');if(!b)return;Object.assign(box.style,{left:(img.offsetLeft+b.x*img.clientWidth)+'px',top:(img.offsetTop+b.y*img.clientHeight)+'px',width:(b.w*img.clientWidth)+'px',height:(b.h*img.clientHeight)+'px'});box.hidden=false;};$('queueFullFrame').src=row.frame_url;$('queueVideoLink').hidden=!row.review_url;if(row.review_url)$('queueVideoLink').href=row.review_url;$('queueFrame').showModal();};links.append(inspect);
  if(row.review_url){const link=el('a','Review video');link.href=row.review_url;links.append(link);}
  const omit=el('button','Omit data');omit.type='button';omit.title='Delete this object and its unshared local media';omit.onclick=async()=>{if(pending.has(row.id)||omit.disabled)return;deleting.add(row.id);omit.disabled=true;omit.textContent='Deleting…';n.querySelectorAll('button,input').forEach(b=>b.disabled=true);try{const result=await api('/api/objects/omit',{id:row.id});if(!result.deleted)throw Error('Deletion not confirmed');deletedIds.add(row.id);rows.delete(row.id);selected.delete(row.id);n.remove();selection();notice(result.cleanup_pending?'Object deleted; shared recording cleanup is pending.':'Object and unshared media deleted.');for(const [key]of views){const included=key==='all'||(key==='human_reviewed_anomalous'?row.human_reviewed&&row.label==='anomalous':key==='human_reviewed'?row.human_reviewed:key==='needs_review'?!row.human_reviewed:row.label===key);if(included&&Number.isFinite(tabCounts[key]))tabCounts[key]=Math.max(0,tabCounts[key]-1);}renderTabs();$('queueEmpty').hidden=rows.size>0;}catch(e){omit.textContent='Omit data';notice('Delete needs attention: '+e.message);}finally{deleting.delete(row.id);selection();}};if(window.FIELD_PUBLIC_READ_ONLY!==true)links.append(omit);
  const error=el('p');error.className='queue-error';error.setAttribute('role','status');
  if(pending.has(row.id))error.textContent='Label retained on this device; waiting for confirmation.';
  actions.append(grid,links,error);const box=el('input');box.type='checkbox';box.className='frame-select';box.setAttribute('aria-label','Select object for bulk classification');box.onclick=e=>{e.stopPropagation();select(row.id,e);};
  n.addEventListener('click',e=>{if(e.shiftKey&&!e.target.closest('a,input')){e.preventDefault();e.stopImmediatePropagation();select(row.id,e);}},true);
  n.append(image,badge,actions,box);return n;
 }
 const tabButtons=new Map(),tabCounts={};let completeCounts=false;
 function renderTabs(counts,indexing=false){
  if(counts&&(!indexing||!completeCounts)){
   for(const [key]of views)if(Number.isFinite(counts[key]))tabCounts[key]=counts[key];
   if(!indexing)completeCounts=true;
  }
  $('objectViews').setAttribute('aria-busy',String(indexing));
  for(const [key,name]of views){
   let b=tabButtons.get(key);
   if(!b){
    b=el('button');b.type='button';const label=el('span',name),count=el('span');count.className='tab-count';b.append(label,count);
    b.onclick=()=>{if(view===key)return;view=key;history.replaceState(null,'','/label-videos?view='+view);reset();};tabButtons.set(key,b);$('objectViews').append(b);
   }
   const count=b.querySelector('.tab-count'),value=tabCounts[key];
   const text=value===undefined?'…':value.toLocaleString('en-US',{notation:'compact',maximumFractionDigits:1})+(indexing&&!completeCounts?'+':'');
   if(count.textContent!==text)count.textContent=text;
   count.title=indexing&&completeCounts?'Updating; showing the last complete count.':'';
   b.setAttribute('aria-pressed',String(view===key));
  }
 }

 async function reset(){version++;loading=false;cursor='';more=true;rows.clear();selected.clear();anchor=null;$('detectionQueue').replaceChildren();renderTabs(undefined,true);selection();await load();}
 async function load(){if(loading||!more)return;loading=true;const rev=version;$('moreDetections').disabled=true;
  try{const data=await api('/api/objects?'+new URLSearchParams({view,before:cursor,limit:100}));if(rev!==version)return;if(data.index_error&&data.ready===false)notice('Could not load detections: '+data.index_error);cursor=data.next_cursor||'';more=!!cursor;renderTabs(data.counts,data.indexing||data.ready===false);
   for(const row of data.items)if(!rows.has(row.id)&&!deletedIds.has(row.id)){rows.set(row.id,row);$('detectionQueue').append(card(row));}
   $('queueStatus').textContent=data.ready===false?(data.index_error?'Library could not be loaded: '+data.index_error:'Loading the object library…'):(data.indexing?'Updating library…':'');$('queueEmpty').hidden=rows.size>0||data.ready===false||data.indexing;if(data.ready===false&&data.indexing)setTimeout(()=>{if(rev===version)reset();},2000);$('moreDetections').hidden=!more;selection();
  }catch(e){if(rev===version)notice(e.message);}finally{if(rev===version){loading=false;$('moreDetections').disabled=false;}}
 }
 function enqueue(row,label,bulk=false){if(pending.has(row.id)||deleting.has(row.id))return;const item={row,body:{id:row.id,label,queued_at:Date.now()/1000,request_id:Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('')}};
  try{localStorage.setItem(prefix+item.body.request_id,JSON.stringify(item));}catch{notice('Device storage unavailable. Label was not queued.');return;}
  pending.set(row.id,item);selected.delete(row.id);if(!bulk){selection();drain();}
 }
 async function drain(){if(draining||!token)return;draining=true;let saved=0,failures=0;
  try{const work=[...pending];for(let offset=0;offset<work.length;offset+=50){const batch=work.slice(offset,offset+50);let results;
   try{const response=await api('/api/objects/labels',{items:batch.map(([,item])=>item.body)});results=new Map((response.results||[]).map(r=>[r.request_id,r]));}
   catch(e){notice('Save needs attention: '+e.message+'. Your labels are retained on this device.');failures++;break;}
   for(const [id,item]of batch){const result=results.get(item.body.request_id);
    if(result?.discarded){localStorage.removeItem(prefix+item.body.request_id);if(item.legacyKey)localStorage.removeItem(item.legacyKey);pending.delete(id);continue;}
    if(!result?.saved){failures++;continue;}
    localStorage.removeItem(prefix+item.body.request_id);if(item.legacyKey)localStorage.removeItem(item.legacyKey);pending.delete(id);saved++;
    const row=rows.get(id);if(row){row.label=result.label;row.human_reviewed=true;const old=[...$('detectionQueue').children].find(n=>n.dataset.id===id);if(matches(row)){old?.replaceWith(card(row));}else{old?.remove();rows.delete(id);}}selected.delete(id);
   }
   notice(saved+' saved · '+pending.size+' waiting for confirmation');selection();
  }}finally{draining=false;selection();if(failures)notice(saved+' saved · '+pending.size+' still need confirmation; labels are retained on this device.');else if(saved)notice(saved+' object'+(saved===1?'':'s')+' reviewed');if(saved&&!pending.size&&!selected.size)await reset();}
 }
 for(const label of ['anomalous','not_anomalous']){const b=el('button',pretty(label));b.onclick=()=>{for(const id of [...selected])enqueue(rows.get(id),label,true);selection();drain();};$('bulkCategories').append(b);}
 new ResizeObserver(()=>document.documentElement.style.setProperty('--bulk-review-height',$('bulkReview').getBoundingClientRect().height+'px')).observe($('bulkReview'));
 $('selectAll').onclick=()=>{for(const id of rows.keys())if(!pending.has(id))selected.add(id);selection();};$('clearSelection').onclick=()=>{selected.clear();anchor=null;selection();};
 $('moreDetections').onclick=load;$('closeQueueFrame').onclick=()=>$('queueFrame').close();
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){selected.clear();selection();}});
 try{for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);if(k.startsWith(prefix)||k.startsWith('field-station.pending-label.')){const item=JSON.parse(localStorage.getItem(k));if(item.row?.kind==='video')continue;if(!k.startsWith(prefix))item.legacyKey=k;pending.set(item.row.id,item);}}}catch{notice('Could not restore pending reviews.');}
 window.addEventListener('station-backlog-cleared',()=>{void reset();});
 window.addEventListener('online',drain);window.addEventListener('station-reconnected',e=>{token=e.detail.token;drain();});
 setInterval(()=>{if(pending.size)drain();},5000);
 // Refresh only when idle; never replace a selection or open inspection.
 setInterval(()=>{if(!document.hidden&&!loading&&rows.size<=100&&!selected.size&&!pending.size&&!deleting.size&&!$('queueFrame').open&&window.scrollY<150&&!document.querySelector('.detection-card:hover,.controls-open'))reset();},15000);
 new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&rows.size)load();},{rootMargin:'200px'}).observe($('moreDetections'));
 api('/api/labeled-frames/token').then(async d=>{const cutoff=d.pending_reset?.epoch||0;let discarded=0;for(const [id,item] of pending){if(cutoff&&(!item.body.queued_at||item.body.queued_at<=cutoff)){localStorage.removeItem(prefix+item.body.request_id);if(item.legacyKey)localStorage.removeItem(item.legacyKey);pending.delete(id);discarded++;}}token=d.token;await reset();if(discarded)notice(discarded+' pending labels discarded as requested');await drain();}).catch(e=>{notice(e.message);});
})();
