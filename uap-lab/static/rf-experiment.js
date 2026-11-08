/* RF preparation is private; choosing a profile never grants transmit authority. */
'use strict';
(()=>{
 if(window.FIELD_PUBLIC_READ_ONLY===true)return;
 const target=document.getElementById('rfOverlay');if(!target)return;
 const panel=document.createElement('details');panel.className='rf-experiment';
 panel.innerHTML=`<summary>RF message</summary><form><label>Operating profile<select name="profile" aria-label="RF operating profile"></select></label><p class="rf-profile-description"></p><label>Message<textarea name="message" rows="2" maxlength="256" placeholder="Enter a message" required></textarea></label><div class="rf-message-actions"><button type="submit">Dry run</button><button type="button" disabled title="Operator setup and hardware validation required">Transmit</button></div><p class="rf-message-result" role="status">Loading operating profiles…</p></form>`;
 target.prepend(panel);
 const form=panel.querySelector('form'),select=form.elements.profile,message=form.elements.message,result=panel.querySelector('[role=status]'),description=panel.querySelector('.rf-profile-description'),run=form.querySelector('[type=submit]');
 let profiles=[],requestToken;run.disabled=true;
 select.onchange=()=>{const profile=profiles.find(p=>p.id===select.value);description.textContent=profile?`${profile.description} ${profile.preset.label}.`:'';result.textContent='RF transmission locked. Dry run is available.';};
 api('/api/rf/experiment').then(state=>{profiles=state.profiles;requestToken=state.token;for(const p of profiles){const option=document.createElement('option');option.value=p.id;option.textContent=p.label;select.append(option);}select.onchange();run.disabled=false;}).catch(e=>{result.textContent=e.message;});
 form.onsubmit=async event=>{event.preventDefault();run.disabled=true;result.textContent='Checking message…';try{const response=await fetch('/api/rf/experiment',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':requestToken},body:JSON.stringify({profile:select.value,message:message.value,action:'preview'}),signal:AbortSignal.timeout(10000)});const state=await response.json();if(!response.ok)throw Error(state.error||'Dry run failed.');result.textContent=`${state.bytes} bytes · ${state.bits} bits · UTF-8. ${state.message}`;}catch(e){result.textContent=e.message;}finally{run.disabled=false;}};
})();
