'use strict';
(()=>{
 const $=id=>document.getElementById(id);const source='detections';let token='',cursor='',loading=false,more=true,total=0,labels=[],last=null;const shown=new Set();let reviewRevision=0,reconciling=false;
 const selected=new Set(),rows=new Map();let selectionAnchor=null;
 const pretty=s=>s==='not_anomalous'?'Not Anomalous':s==='cloud'?'Cloud/Sky':s==='house'?'Building/Structure':s.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
 async function api(path,body){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),30000);try{const r=await fetch(path,{signal:controller.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok){const e=Error(d.error||'Request failed');e.status=r.status;throw e;}return d;}finally{clearTimeout(timer);}}

 const prefix='field-station.pending-label.';const pending=new Map();let draining=false;
 const canonicalLabel=label=>['airplane','bird','insect','cloud','other_animal','balloon','star','satellite','shooting_star','vehicle','drone'].includes(label)?'not_anomalous':label;
 function updateSelection(){
  const cards=[...$('detectionQueue').children],visible=new Set(cards.map(el=>el.dataset.id));
  for(const id of rows.keys())if(!visible.has(id)&&!pending.has(id))rows.delete(id);
  for(const id of selected)if(!visible.has(id)||pending.has(id))selected.delete(id);
  for(const el of cards){const checked=selected.has(el.dataset.id);el.classList.toggle('selected',checked);const box=el.querySelector('.frame-select');if(box){box.checked=checked;box.disabled=pending.has(el.dataset.id);}}
  $('bulkReview').hidden=!selected.size;$('selectionCount').textContent=selected.size+' selected';
  const buttons=$('bulkCategories');buttons.replaceChildren();
  for(const label of labels){const button=document.createElement('button');button.type='button';button.textContent=pretty(label);button.onclick=()=>{for(const id of [...selected]){const row=rows.get(id);if(row)enqueue(row,label);}updateSelection();};buttons.append(button);}
 }
 function selectFrame(id,event){
  if(pending.has(id))return;
  const ids=[...$('detectionQueue').children].map(el=>el.dataset.id),start=ids.indexOf(selectionAnchor),end=ids.indexOf(id);
  if(event.shiftKey&&start>=0&&end>=0){for(const key of ids.slice(Math.min(start,end),Math.max(start,end)+1))if(!pending.has(key))selected.add(key);}
  else{if(selected.has(id))selected.delete(id);else selected.add(id);selectionAnchor=id;}
  updateSelection();
 }
 $('clearSelection').onclick=()=>{selected.clear();selectionAnchor=null;updateSelection();};
 document.addEventListener('keydown',event=>{if(event.key==='Escape'){selected.clear();selectionAnchor=null;updateSelection();}});
 function persist(item){localStorage.setItem(prefix+item.body.request_id,JSON.stringify(item));}
 function markPending(item,message){const el=[...$('detectionQueue').children].find(e=>e.dataset.id===item.row.id);if(el){el.setAttribute('aria-busy','true');el.querySelectorAll('.category-grid button').forEach(b=>b.disabled=true);el.querySelector('.queue-error').textContent=message;}}
 function enqueue(row,label){if(pending.has(row.id))return;const item={row,body:{id:row.id,kind:row.kind,label,request_id:Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('')}};try{persist(item);}catch{const el=[...$('detectionQueue').children].find(e=>e.dataset.id===row.id);el.querySelector('.queue-error').textContent='Device storage is unavailable. Label was not queued; keep this page open and try again.';return;}pending.set(row.id,item);selected.delete(row.id);updateSelection();markPending(item,'Label retained on this device; waiting for confirmation.');drain();}
 async function drain(){if(draining||!token)return;draining=true;try{for(const [id,item] of pending){if(item.failed)continue;try{const result=await api('/api/label-queue/label',item.body);if(result.saved!==true)throw Error('Save not confirmed');localStorage.removeItem(prefix+item.body.request_id);pending.delete(id);reviewRevision++;last={row:item.row,label:item.body.label,annotation_id:result.annotation_id};const el=[...$('detectionQueue').children].find(e=>e.dataset.id===id);if(el)el.remove();shown.delete(id);if(total!==null)total=Math.max(0,total-1);updateStatus();$('queueSaved').textContent=pretty(item.body.label)+' saved';$('queueToast').hidden=false;$('undoLabel').disabled=false;}catch(e){if(e.status===403){try{token=(await api('/api/labeled-frames/token')).token;}catch{}}else if(e.status>=400&&e.status<500){item.failed=true;persist(item);}markPending(item,(item.failed?'Save needs attention: '+e.message+'. ':'Connection interrupted. ')+'Label retained on this device.');if(!item.failed)break;}}}finally{draining=false;}if([...pending.values()].some(i=>!i.failed))setTimeout(drain,3000);else if(shown.size<12&&more)load();}
 try{for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(key.startsWith(prefix)){const item=JSON.parse(localStorage.getItem(key));if(item?.body?.id&&item?.row?.id){item.row.kind=item.row.kind||item.body.kind||'detection';if(item.row.kind==='video'){localStorage.setItem('field-station.retired-video-label.'+item.body.request_id,JSON.stringify(item));localStorage.removeItem(key);i--;continue;}pending.set(item.row.id,item);}}}}catch(e){$('queueStatus').textContent='Unable to restore pending labels: '+e.message;}
 window.addEventListener('online',drain);
 function updateStatus(){updateSelection();$('queueStatus').textContent=(total===null?shown.size+' items ready for review':total+' items to review');$('queueEmpty').hidden=shown.size>0||more;$('moreDetections').hidden=!more||shown.size===0;}
 function card(row){
  rows.set(row.id,row);
  const el=document.createElement('article');el.className='detection-card';el.dataset.id=row.id;el.dataset.kind=row.kind;
  const image=document.createElement('button');image.type='button';image.className='detection-image';image.setAttribute('aria-label','Show labeling categories');image.setAttribute('aria-expanded','false');const img=document.createElement('img');img.src=row.image_url;img.alt=row.kind==='video'?(row.title||'Unreviewed video'):'Unreviewed detected object';img.width=320;img.height=320;img.loading='lazy';img.decoding='async';image.append(img);
  image.onclick=event=>{selectFrame(row.id,event);if(event.shiftKey)return;const open=!el.classList.contains('controls-open');document.querySelectorAll('.controls-open').forEach(e=>e.classList.remove('controls-open'));el.classList.toggle('controls-open',open);image.setAttribute('aria-expanded',String(open));};
  const actions=document.createElement('div');actions.className='category-actions';const grid=document.createElement('div');grid.className='category-grid';const error=document.createElement('p');error.className='queue-error';error.setAttribute('role','alert');
  for(const category of labels){const b=document.createElement('button');b.type='button';b.textContent=pretty(category);b.setAttribute('aria-label','Label as '+pretty(category));b.onclick=()=>enqueue(row,category);b.title='Save this frame as '+pretty(category)+' for training';grid.append(b);}
  if(pending.has(row.id)){el.setAttribute('aria-busy','true');grid.querySelectorAll('button').forEach(b=>b.disabled=true);error.textContent='Label retained on this device; waiting for confirmation.';}

  const inspect=document.createElement('button');inspect.type='button';inspect.textContent='Inspect frame';inspect.onclick=()=>{$('queueFullFrame').src=row.frame_url;$('queueVideoLink').href=row.review_url;$('queueFrame').showModal();};const video=document.createElement('a');video.textContent='Review video';video.href=row.review_url;const links=document.createElement('div');links.className='review-actions';if(row.kind!=='video')links.append(inspect);links.append(video);actions.append(grid,links,error);const select=document.createElement('input');select.type='checkbox';select.className='frame-select';select.setAttribute('aria-label','Select frame for bulk classification');select.disabled=pending.has(row.id);select.onclick=event=>{event.stopPropagation();selectFrame(row.id,event);};el.addEventListener('click',event=>{if(event.target===actions||event.target===el){selectFrame(row.id,event);}});el.addEventListener('click',event=>{if(event.shiftKey&&!event.target.closest('a,.frame-select')){event.preventDefault();event.stopImmediatePropagation();selectFrame(row.id,event);}},true);el.append(image,actions,select);el.addEventListener('keydown',e=>{if(e.key==='Escape'){el.classList.remove('controls-open');image.focus();image.blur();}});return el;
 }
 async function queuePage(before=''){
  // Server cursors bound filesystem scanning, not visible pages. Collect a full
  // visible page before changing the DOM, including across dismissed records.
  const items=[],visited=new Set();let next=before,data;
  do{
   if(visited.has(next))throw Error('Queue cursor did not advance');visited.add(next);
   data=await api('/api/label-queue?limit='+Math.min(100,100-items.length)+'&source='+encodeURIComponent(source)+'&before='+encodeURIComponent(next));
   items.push(...data.items);next=data.next_cursor||'';
  }while(next&&items.length<100);
  return {...data,items,next_cursor:next||null,total:!before&&!next?items.length:null};
 }
 async function load(){if(loading||!more)return;loading=true;const revision=reviewRevision;$('moreDetections').disabled=true;try{const data=await queuePage(cursor);if(revision!==reviewRevision){setTimeout(load,0);return;}labels=data.labels;total=data.total;cursor=data.next_cursor||'';more=!!data.next_cursor;for(const row of data.items)if(!shown.has(row.id)){shown.add(row.id);$('detectionQueue').append(card(row));}updateStatus();}catch(e){$('queueStatus').textContent=e.message;$('moreDetections').hidden=false;}finally{loading=false;$('moreDetections').disabled=false;}if(!shown.size&&more)setTimeout(load,100);}
 async function refreshTop(){
  if(document.hidden||selected.size||window.scrollY>150||loading||document.querySelector('.controls-open,[aria-busy="true"],.detection-card:hover,.detection-card:focus-within')||$('queueFrame').open)return;
  loading=true;const revision=reviewRevision;
  try{const data=await queuePage();if(revision!==reviewRevision||selected.size)return;labels=data.labels;total=data.total;const existing=new Map([...$('detectionQueue').children].map(el=>[el.dataset.id,el]));const paged=shown.size>100;if(!paged){cursor=data.next_cursor||'';more=!!data.next_cursor;}const ordered=[];for(const row of data.items){ordered.push(existing.get(row.id)||card(row));existing.delete(row.id);}if(paged)ordered.push(...existing.values());const current=[...$('detectionQueue').children];if(current.length!==ordered.length||ordered.some((el,i)=>el!==current[i]))$('detectionQueue').replaceChildren(...ordered);shown.clear();for(const el of ordered)shown.add(el.dataset.id);updateStatus();}
  catch{}finally{loading=false;}
  if(!shown.size&&more)load();
 }
 async function reconcileReviewed(){
  if(document.hidden||reconciling||!token||!shown.size)return;
  reconciling=true;const revision=reviewRevision;
  try{
   const items=[...$('detectionQueue').children].map(el=>({id:el.dataset.id,kind:el.dataset.kind,...(pending.has(el.dataset.id)?{request_id:pending.get(el.dataset.id).body.request_id,pending_label:pending.get(el.dataset.id).body.label}:{})}));const reviewed=[],confirmed=[],receipts=[];
   for(let offset=0;offset<items.length;offset+=500){const result=await api('/api/label-queue/status',{items:items.slice(offset,offset+500)});reviewed.push(...result.reviewed);confirmed.push(...(result.confirmed||[]));receipts.push(...(result.acknowledged||[]));}
   if(revision!==reviewRevision)return;
   let acknowledged=0;
   for(const receipt of receipts){const item=pending.get(receipt.id);if(item&&item.body.request_id===receipt.request_id){localStorage.removeItem(prefix+item.body.request_id);pending.delete(receipt.id);acknowledged++;}}
   for(const saved of confirmed){const item=pending.get(saved.id);if(item&&item.row.kind===saved.kind&&canonicalLabel(item.body.label)===canonicalLabel(saved.label)){localStorage.removeItem(prefix+item.body.request_id);pending.delete(saved.id);acknowledged++;}}
   const ids=new Set([...reviewed,...receipts].map(row=>row.id));let removed=0;
   for(const el of [...$('detectionQueue').children])if(ids.has(el.dataset.id)&&!pending.has(el.dataset.id)){shown.delete(el.dataset.id);el.remove();removed++;}
   if(acknowledged||removed){reviewRevision++;if(total!==null)total=Math.max(0,total-removed);updateStatus();if(shown.size<12&&more)load();if(acknowledged){$('queueSaved').textContent=acknowledged+' saved '+(acknowledged===1?'label confirmed':'labels confirmed');$('queueToast').hidden=false;$('undoLabel').disabled=!last;}}
  }catch(e){if(e.status===403){try{token=(await api('/api/labeled-frames/token')).token;}catch{}}}finally{reconciling=false;}
 }
 setInterval(reconcileReviewed,5000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)reconcileReviewed();});
 setInterval(refreshTop,15000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshTop();});
 $('moreDetections').onclick=load;new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&shown.size)load();},{rootMargin:'200px'}).observe($('moreDetections'));
 $('undoLabel').onclick=async()=>{if(!last)return;const undo=last;$('undoLabel').disabled=true;try{if(undo.row.kind==='video')await api('/api/delete-annotation',{id:undo.row.id,annotation:undo.annotation_id});else await api('/api/email-review/delete',{id:undo.row.id,sample_id:undo.row.id});reviewRevision++;if(!shown.has(undo.row.id)){shown.add(undo.row.id);$('detectionQueue').prepend(card(undo.row));if(total!==null)total++;}last=null;$('queueToast').hidden=true;updateStatus();}catch(e){$('queueSaved').textContent=e.message;$('undoLabel').disabled=false;}};
 $('closeQueueFrame').onclick=()=>$('queueFrame').close();window.addEventListener('station-reconnected',e=>{token=e.detail.token;drain();reconcileReviewed();refreshTop();});
 document.querySelectorAll('#queueFilters a').forEach(a=>a.setAttribute('aria-current',(a.dataset.source===source)?'page':'false'));
 api('/api/labeled-frames/token').then(d=>{token=d.token;return load().then(()=>{for(const item of pending.values()){if(!shown.has(item.row.id)){shown.add(item.row.id);$('detectionQueue').prepend(card(item.row));}if(item.failed)markPending(item,'Save needs attention; label retained on this device. Open its video to check the saved label.');}drain();reconcileReviewed();});}).catch(e=>{$('queueStatus').textContent=e.message;});
})();
