'use strict';
(()=>{
 const $=id=>document.getElementById(id),views=[['all','All detections'],['anomalous','Anomalous'],['not_anomalous','Not Anomalous'],['needs_review','Needs review'],['human_reviewed','Human-reviewed']];
 let view=new URLSearchParams(location.search).get('view')||'all',token='',cursor='',more=true,loading=false,version=0,anchor=null,draining=false;
 if(!views.some(([v])=>v===view))view='all';
 const rows=new Map(),selected=new Set(),pending=new Map(),prefix='field-station.object-review.';
 const pretty=label=>label==='anomalous'?'Anomalous':'Not Anomalous';
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 async function api(path,body){const r=await fetch(path,{signal:AbortSignal.timeout(30000),...(body?{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
 let noticeTimer;function notice(text){clearTimeout(noticeTimer);$('queueSaved').textContent=text;$('queueToast').hidden=false;noticeTimer=setTimeout(()=>{$('queueToast').hidden=true;},6000);}
 function matches(row){return view==='all'||(view==='needs_review'?!row.human_reviewed:view==='human_reviewed'?row.human_reviewed:row.label===view);}
 function selection(){
  const cards=new Map([...$('detectionQueue').children].map(n=>[n.dataset.id,n]));for(const [id,row] of rows){const card=cards.get(id);if(!card)continue;card.classList.toggle('selected',selected.has(id));card.querySelector('.frame-select').checked=selected.has(id);card.querySelectorAll('button,input').forEach(b=>b.disabled=pending.has(id));}
  $('bulkReview').hidden=!selected.size;$('selectionCount').textContent=selected.size+' selected';
 }
 function select(id,event){if(pending.has(id))return;const ids=[...rows.keys()],a=ids.indexOf(anchor),b=ids.indexOf(id);if(event.shiftKey&&a>=0){for(const k of ids.slice(Math.min(a,b),Math.max(a,b)+1))if(!pending.has(k))selected.add(k);}else{selected.has(id)?selected.delete(id):selected.add(id);anchor=id;}selection();}
 function card(row){
  const n=el('article');n.className='detection-card';n.dataset.id=row.id;
  const image=el('button');image.className='detection-image';image.type='button';image.setAttribute('aria-label','Select '+pretty(row.label)+' object');const img=el('img');img.src=row.image_url;img.alt=pretty(row.label)+' detected object';img.loading='lazy';image.append(img);image.onclick=e=>{select(row.id,e);n.classList.toggle('controls-open');};
  const badge=el('span',pretty(row.label)+' · '+(row.human_reviewed?'Human-reviewed':'Needs review'));badge.className='object-label';
  const actions=el('div');actions.className='category-actions';const grid=el('div');grid.className='category-grid';
  for(const label of ['anomalous','not_anomalous']){const b=el('button',pretty(label));b.type='button';b.setAttribute('aria-label','Label as '+pretty(label));b.onclick=()=>enqueue(row,label);grid.append(b);}
  const links=el('div');links.className='review-actions';const inspect=el('button','Inspect frame');inspect.onclick=()=>{$('queueFrameBox').hidden=true;$('queueFullFrame').onload=()=>{const b=row.frame_bounds,img=$('queueFullFrame'),box=$('queueFrameBox');if(!b)return;Object.assign(box.style,{left:(img.offsetLeft+b.x*img.clientWidth)+'px',top:(img.offsetTop+b.y*img.clientHeight)+'px',width:(b.w*img.clientWidth)+'px',height:(b.h*img.clientHeight)+'px'});box.hidden=false;};$('queueFullFrame').src=row.frame_url;$('queueVideoLink').hidden=!row.review_url;if(row.review_url)$('queueVideoLink').href=row.review_url;$('queueFrame').showModal();};links.append(inspect);
  if(row.review_url){const link=el('a','Review video');link.href=row.review_url;links.append(link);}
  const error=el('p');error.className='queue-error';error.setAttribute('role','status');
  if(pending.has(row.id))error.textContent='Label retained on this device; waiting for confirmation.';
  actions.append(grid,links,error);const box=el('input');box.type='checkbox';box.className='frame-select';box.setAttribute('aria-label','Select object for bulk classification');box.onclick=e=>{e.stopPropagation();select(row.id,e);};
  n.addEventListener('click',e=>{if(e.shiftKey&&!e.target.closest('a,input')){e.preventDefault();e.stopImmediatePropagation();select(row.id,e);}},true);
  n.append(image,badge,actions,box);return n;
 }
 function renderTabs(counts={},indexing=false){$('objectViews').replaceChildren();for(const [key,name]of views){const b=el('button',name+(counts[key]===undefined?'':' ('+(indexing?(counts[key]?counts[key]+'+':'…'):counts[key])+')'));b.type='button';b.setAttribute('aria-pressed',String(view===key));b.onclick=()=>{view=key;history.replaceState(null,'','/label-videos?view='+view);reset();};$('objectViews').append(b);}}
 async function reset(){version++;loading=false;cursor='';more=true;rows.clear();selected.clear();anchor=null;$('detectionQueue').replaceChildren();renderTabs();selection();await load();}
 async function load(){if(loading||!more)return;loading=true;const rev=version;$('moreDetections').disabled=true;
  try{const data=await api('/api/objects?'+new URLSearchParams({view,before:cursor,limit:100}));if(rev!==version)return;cursor=data.next_cursor||'';more=!!cursor;renderTabs(data.counts,data.indexing);
   for(const row of data.items)if(!rows.has(row.id)){rows.set(row.id,row);$('detectionQueue').append(card(row));}
   $('queueStatus').textContent=data.ready===false?(data.index_error?'Library could not be loaded: '+data.index_error:'Loading the object library…'):data.total+' objects'+(data.indexing?' · updating library':'');$('queueEmpty').hidden=rows.size>0||data.ready===false||data.indexing;if(data.ready===false&&data.indexing)setTimeout(()=>{if(rev===version)reset();},2000);$('moreDetections').hidden=!more;selection();
  }catch(e){if(rev===version)$('queueStatus').textContent=e.message;}finally{if(rev===version){loading=false;$('moreDetections').disabled=false;}}
 }
 function enqueue(row,label,bulk=false){if(pending.has(row.id))return;const item={row,body:{id:row.id,label,request_id:Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('')}};
  try{localStorage.setItem(prefix+item.body.request_id,JSON.stringify(item));}catch{notice('Device storage unavailable. Label was not queued.');return;}
  pending.set(row.id,item);selected.delete(row.id);if(!bulk){selection();drain();}
 }
 async function drain(){if(draining||!token)return;draining=true;let saved=0;
  try{for(const [id,item]of pending){try{const result=await api('/api/objects/label',item.body);if(!result.saved)throw Error('Save not confirmed');localStorage.removeItem(prefix+item.body.request_id);if(item.legacyKey)localStorage.removeItem(item.legacyKey);pending.delete(id);saved++;notice(saved+' saved · '+pending.size+' waiting for confirmation');
    const row=rows.get(id);if(row){row.label=result.label;row.human_reviewed=true;const old=[...$('detectionQueue').children].find(n=>n.dataset.id===id);if(matches(row)){old?.replaceWith(card(row));}else{old?.remove();rows.delete(id);}}selected.delete(id);
   }catch(e){notice('Save needs attention: '+e.message+'. Your label is retained on this device.');break;}}
  }finally{draining=false;selection();if(saved){notice(saved+' object'+(saved===1?'':'s')+' reviewed');if(!pending.size&&!selected.size)await reset();}}
 }
 for(const label of ['anomalous','not_anomalous']){const b=el('button',pretty(label));b.onclick=()=>{for(const id of [...selected])enqueue(rows.get(id),label,true);selection();drain();};$('bulkCategories').append(b);}
 $('selectAll').onclick=()=>{for(const id of rows.keys())if(!pending.has(id))selected.add(id);selection();};$('clearSelection').onclick=()=>{selected.clear();anchor=null;selection();};
 $('moreDetections').onclick=load;$('closeQueueFrame').onclick=()=>$('queueFrame').close();
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){selected.clear();selection();}});
 try{for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);if(k.startsWith(prefix)||k.startsWith('field-station.pending-label.')){const item=JSON.parse(localStorage.getItem(k));if(item.row?.kind==='video')continue;if(!k.startsWith(prefix))item.legacyKey=k;pending.set(item.row.id,item);}}}catch{notice('Could not restore pending reviews.');}
 window.addEventListener('online',drain);window.addEventListener('station-reconnected',e=>{token=e.detail.token;drain();});
 setInterval(()=>{if(pending.size)drain();},5000);
 // Refresh only when idle; never replace a selection or open inspection.
 setInterval(()=>{if(!document.hidden&&!loading&&rows.size<=100&&!selected.size&&!pending.size&&!$('queueFrame').open&&window.scrollY<150&&!document.querySelector('.detection-card:hover,.controls-open'))reset();},15000);
 new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&rows.size)load();},{rootMargin:'200px'}).observe($('moreDetections'));
 api('/api/labeled-frames/token').then(async d=>{token=d.token;await reset();await drain();}).catch(e=>{$('queueStatus').textContent=e.message;});
})();
