/* Private, explicitly armed RF control. Never auto-send or retry transmissions. */
'use strict';
(()=>{
 if(window.FIELD_PUBLIC_READ_ONLY===true)return;
 const target=document.getElementById('rfOverlay');if(!target)return;
 const panel=document.createElement('dialog');panel.className='rf-experiment';panel.setAttribute('aria-labelledby','rfDialogTitle');
 const trigger=document.createElement('button');trigger.type='button';trigger.className='rf-message-trigger';trigger.textContent='RF message';trigger.onclick=()=>panel.showModal();
 panel.innerHTML=`<header class="rf-dialog-header"><h2 id="rfDialogTitle">RF message</h2><button type="button" id="rfClose" aria-label="Close RF message">×</button></header>
 <div class="rf-body"><p class="rf-legal">Live RF is for licensed, authorized operators. You are responsible for lawful operation and avoiding interference. Misuse may result in fines, equipment seizure, or other penalties. Presets do not grant authorization. <a href="https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97" target="_blank" rel="noopener noreferrer">FCC amateur radio rules</a></p>
 <label>Operating profile<select id="rfProfile" aria-label="RF operating profile"></select></label>
 <p id="rfProfileDescription"></p>
 <details id="rfSetup"><summary>Operator setup · saved once</summary>
 <form id="rfSetupForm">
 <label>US station callsign<input name="callsign" autocomplete="off" maxlength="6" required></label>
 <label>Operator license<select name="license_class"><option value="technician">Technician</option><option value="general">General</option><option value="extra">Amateur Extra</option></select></label>
 <label>Transmit radio<select name="tx_serial"></select></label>
 <p>The other radio keeps receiving. This does not confirm that it decoded your message.</p>
 <p>441.500 MHz · Morse/CW, 20 WPM. Maximum burst 30 seconds; 60-second cooldown. TX gain 0 dB; RF amplifier and antenna power off.</p>
 <label>Measured conducted output (dBm)<input name="measured_dbm" type="number" min="-100" max="0" step="any" placeholder="Measure using this preset; maximum 0 dBm" required></label>
 <label>Antenna/load, filtering, attenuation, and measurement notes<textarea name="hardware_notes" rows="3" minlength="10" maxlength="2000" required></textarea></label>
 <label class="rf-check"><input name="hardware_verified" type="checkbox" required>RF chain, output power, and unwanted emissions verified for this exact preset.</label>
 <label class="rf-check"><input name="authorization_confirmed" type="checkbox" required>I accept responsibility for lawful operation, hold the required authorization, and have checked local channel use.</label>
 <label class="rf-check"><input name="shielding_verified" type="checkbox">Shielded test arrangement verified to contain RF (required for shielded mode).</label>
 <label id="rfCurrentPasswordLabel">Current operator passphrase<input name="current_password" type="password" autocomplete="current-password" maxlength="256"></label>
 <label id="rfNewPasswordLabel">Set operator passphrase<input name="password" type="password" autocomplete="new-password" minlength="12" maxlength="256"></label>
 <button type="submit">Save operator setup</button><p id="rfSetupStatus" role="status"></p>
 </form></details>
 <label>Operator passphrase<input id="rfArmPassword" type="password" autocomplete="current-password" maxlength="256"></label>
 <label class="rf-check"><input id="rfOperatorPresent" type="checkbox">I am the designated control operator supervising this session.</label>
 <label class="rf-check"><input id="rfChannelClear" type="checkbox">I have checked the channel and the selected test arrangement.</label>
 <div class="rf-arm-row"><label for="rfArm">Arm transmitter</label><input id="rfArm" type="checkbox" role="switch" disabled></div>
 <form id="rfMessageForm"><label>Message<textarea name="message" rows="2" maxlength="64" placeholder="A–Z, digits, spaces, . , ? / = -" required></textarea></label>
 <div class="rf-message-actions"><button type="submit" value="preview">Dry run</button><button type="submit" value="transmit" id="rfSend" disabled>Transmit</button><button type="button" id="rfStop">Stop</button></div></form>
 <p id="rfResult" role="status">Loading RF status…</p>
 </div>`;
 target.prepend(trigger);document.body.append(panel);
 const q=id=>panel.querySelector('#'+id),profile=q('rfProfile'),setup=q('rfSetupForm'),message=q('rfMessageForm'),arm=q('rfArm'),send=q('rfSend'),result=q('rfResult');
 let token,lease=null,profiles=[],state=null,polling=false,changing=false,heartbeatBusy=false;
 async function request(path,body){const r=await fetch(path,{...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)}),signal:AbortSignal.timeout(10000)});const d=await r.json();if(!r.ok)throw Error(d.error||'RF request failed');return d;}
 function description(){const p=profiles.find(p=>p.id===profile.value);q('rfProfileDescription').textContent=p?`${p.description} ${p.preset.label}.`:'';}
 function controls(){const supported=profile.value==='shielded'||profile.value.startsWith('ham-');if(!changing)arm.checked=!!lease&&!!state?.armed;arm.disabled=changing||(!arm.checked&&(!state?.configured||!supported||state?.busy||state?.cooldown_seconds>0));send.disabled=changing||!lease||!state?.transmit_enabled||state?.busy;}
 function populate(s){for(const [key,value] of Object.entries(s.setup)){const field=setup.elements[key];if(!field)continue;if(field.type==='checkbox')field.checked=value===true;else field.value=value??'';}q('rfCurrentPasswordLabel').hidden=!s.configured;setup.elements.current_password.required=s.configured;setup.elements.password.required=!s.configured;q('rfNewPasswordLabel').firstChild.textContent=s.configured?'New passphrase (optional)':'Set operator passphrase (12+ characters)';}
 async function poll(){if(polling||changing)return;polling=true;try{const s=await request('/api/rf/experiment');token=s.token;state=s;if(!profiles.length){profiles=s.profiles;for(const p of profiles){const o=new Option(p.id==='experimental'?'Experimental authorization (not supported)':p.label,p.id);o.disabled=p.id==='experimental';profile.add(o);}for(const r of s.radios)setup.elements.tx_serial.add(new Option(`${r.serial.slice(-8)} · currently ${r.role==='rf'?'narrow receiver':'wide receiver'}`,r.serial));populate(s);description();if(!s.configured)q('rfSetup').open=true;}if(lease&&!s.armed)lease=null;controls();if(s.busy)result.textContent=s.state.phase==='transmitting'?'Transmitting…':'Preparing transmission…';else if(s.state.id&&s.state.id!==panel.dataset.finished){panel.dataset.finished=s.state.id;result.textContent=s.state.error||s.state.message||s.state.phase;if(s.state.restore_error)result.textContent+=' Receiver restart needs attention: '+s.state.restore_error;}else if(!panel.dataset.ready){result.textContent=s.reason;panel.dataset.ready='true';}}catch(e){result.textContent=e.message;send.disabled=true;arm.disabled=!lease;}finally{polling=false;}}
 setup.onsubmit=async e=>{e.preventDefault();const body={};for(const key of ['callsign','license_class','tx_serial','hardware_notes','password','current_password'])body[key]=setup.elements[key].value;body.measured_dbm=Number(setup.elements.measured_dbm.value);for(const key of ['hardware_verified','authorization_confirmed','shielding_verified'])body[key]=setup.elements[key].checked;changing=true;controls();try{state=await request('/api/rf/setup',body);lease=null;populate(state);profile.value='ham-'+state.setup.license_class;description();setup.elements.password.value='';setup.elements.current_password.value='';q('rfSetupStatus').textContent='Setup saved. Transmitter remains disarmed.';q('rfSetup').open=false;}catch(e){q('rfSetupStatus').textContent=e.message;}finally{changing=false;controls();}};
 async function disarm(){lease=null;send.disabled=true;arm.checked=false;try{state=await request('/api/rf/disarm',{});result.textContent='Disarmed. Any active transmission is stopping.';}catch(e){result.textContent='Connection lost. The transmitter watchdog stops RF when heartbeats expire.';}controls();}
 arm.onchange=async()=>{if(!arm.checked){await disarm();return;}changing=true;controls();try{state=await request('/api/rf/arm',{profile:profile.value,password:q('rfArmPassword').value,operator_present:q('rfOperatorPresent').checked,channel_clear:q('rfChannelClear').checked});lease=state.arm_token;result.textContent='Armed for one burst. Automatically disarms after 60 seconds or lost connection.';}catch(e){lease=null;arm.checked=false;result.textContent=e.message;}finally{changing=false;controls();}};
 q('rfClose').onclick=()=>panel.close();panel.addEventListener('close',()=>{if(lease)void disarm();});q('rfStop').onclick=disarm;profile.onchange=async()=>{description();if(lease)await disarm();controls();};
 message.onsubmit=async e=>{e.preventDefault();const action=e.submitter?.value||'preview';changing=true;controls();try{if(action==='transmit'){const currentLease=lease;send.disabled=true;const r=await request('/api/rf/transmit',{message:message.elements.message.value,arm_token:currentLease});result.textContent=`Transmission ${r.id.slice(0,8)} queued · ${r.seconds.toFixed(1)} seconds.`;}else{const r=await request('/api/rf/experiment',{message:message.elements.message.value,action:'preview',profile:profile.value});result.textContent=`Dry run: ${r.seconds.toFixed(1)} seconds · ${r.encoding} · ${r.frequency_hz/1e6} MHz. No RF transmitted.${r.identification_placeholder?' Configure your callsign; preview uses N0CALL.':''}`;}}catch(e){result.textContent=e.message;if(action==='transmit')await disarm();}finally{changing=false;controls();}};
 setInterval(async()=>{if(!lease||heartbeatBusy)return;heartbeatBusy=true;try{await request('/api/rf/heartbeat',{arm_token:lease});}catch(e){lease=null;send.disabled=true;arm.checked=false;result.textContent='Operator connection lost; transmitter watchdog is stopping RF.';}finally{heartbeatBusy=false;}},1500);
 setInterval(()=>{if(panel.open||lease)void poll();},2000);
 window.addEventListener('pagehide',()=>{lease=null;fetch('/api/rf/disarm',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:'{}',keepalive:true}).catch(()=>{});});
 void poll();
})();
