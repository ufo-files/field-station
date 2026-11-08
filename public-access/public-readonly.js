'use strict';
window.FIELD_PUBLIC_READ_ONLY=true;
if(location.pathname==='/' && location.search)history.replaceState(null,'','/');
(()=>{
 const original=window.fetch.bind(window);
 window.fetch=(input,options={})=>{
  const method=String(options.method||(input instanceof Request?input.method:'GET')).toUpperCase();
  if(!['GET','HEAD'].includes(method))return Promise.resolve(new Response(JSON.stringify({error:'Public access is read only.'}),{status:405,headers:{'Content-Type':'application/json'}}));
  return original(input,options);
 };
 const forbidden=['sessionToggle','trainNow','upload','omit','noTarget','finish','done','test','useSuggestion','removeLabel','linkTrack','selectObservation','save','new','reset','reopen','undoLabel','clearAll'];
 function apply(){
  document.documentElement.classList.add('public-readonly');
  for(const id of forbidden){const el=document.getElementById(id);if(el){el.disabled=true;el.setAttribute('data-public-write','');}}
  if(location.pathname==='/'){const next=document.getElementById('next');if(next){next.disabled=true;next.setAttribute('data-public-write','');}}
  for(const link of document.querySelectorAll('a[href*="view=test"],a[href*="view=label"],a[href^="/email-review"],.review-actions a,#queueVideoLink,#reviewLink'))link.hidden=true;
  for(const e of document.querySelectorAll('.category-grid button,.bulk-categories button,#annotations button.remove,#annotations button.delete')){e.disabled=true;e.setAttribute('data-public-write','');}
  const note=document.querySelector('#queueFrame>p');if(note)note.textContent='Saved detection frame. Public viewing only.';
  const header=document.querySelector('.station-header');
  if(header&&!document.getElementById('publicReadOnly')){const badge=document.createElement('span');badge.id='publicReadOnly';badge.textContent='Read only';badge.setAttribute('aria-label','Public read-only access');header.append(badge);}
 }
 document.addEventListener('click',e=>{const image=e.target.closest('.detection-image');if(image){e.preventDefault();e.stopImmediatePropagation();image.closest('.detection-card')?.querySelector('.review-actions button')?.click();return;}if(e.target.closest('[data-public-write],.category-grid button,.frame-select')){e.preventDefault();e.stopImmediatePropagation();}},true);
 document.addEventListener('submit',e=>{e.preventDefault();e.stopImmediatePropagation();},true);
 document.addEventListener('DOMContentLoaded',()=>{
  apply();let queued=false;
  new MutationObserver(()=>{if(!queued){queued=true;requestAnimationFrame(()=>{queued=false;apply();});}}).observe(document.body,{childList:true,subtree:true});
  setInterval(apply,1000);
 });
})();
