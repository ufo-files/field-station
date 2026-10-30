const $=id=>document.getElementById(id);
let state, busy=false, selected, libraryKey='', recorded=[], audioKey='', frameKey='', settingsDirty=false, settingsRevision=null, galleryFrames=[], galleryPage=0, rfDirty=false, rfSettingsKey='';
const text=(id,value)=>{$(id).textContent=value};
const el=(tag,value,cls)=>{const e=document.createElement(tag);if(value!==undefined)e.textContent=value;if(cls)e.className=cls;return e};
const formatTime=n=>`${Math.floor(n/60).toString().padStart(2,'0')}:${Math.floor(n%60).toString().padStart(2,'0')}`;
function notice(message){text('notice',message);$('notice').hidden=!message}
async function action(path,body={}){
 if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);
 try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Station-Token':state.csrf},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error);notice('');await refresh();return data}
 catch(e){notice(e.message)}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);if(state)renderExperiments(state.experiments);document.querySelectorAll('.session-row button').forEach(b=>{b.disabled=b.textContent==='Recording…'})}
}
$('captureForm').addEventListener('submit',e=>{e.preventDefault();action('/api/start',Object.fromEntries(new FormData(e.target)))});
$('stop').onclick=()=>action('/api/stop');
function scheduleValues(){return {output:$('audioOutput').value,volume:Number($('toneVolume').value),repeat:$('automaticRepeat').value==='repeat',duration_minutes:Number($('autoDuration').value),gap_minutes:Number($('autoGap').value),interval_minutes:Number($('autoInterval').value),video_fps:Number($('videoFps').value),frame_export_mode:$('frameExportMode').value,frame_fps:$('frameExportMode').value==='all'?Number($('videoFps').value):Number($('autoFps').value),ce5_enabled:$('ce5Enabled').checked}}
$('enableAutomatic').onclick=async()=>{if(await action('/api/automatic/enable',scheduleValues())){settingsDirty=false;renderExperiments(state.experiments)}};
$('saveAutomaticSettings').onclick=async()=>{if(await action('/api/automatic/configure',scheduleValues())){settingsDirty=false;renderExperiments(state.experiments);notice('Schedule saved. Changes apply to the next cycle.')}};
for(const id of ['autoDuration','autoGap','autoInterval','autoFps','videoFps','frameExportMode','ce5Enabled','audioOutput','toneVolume','automaticRepeat'])$(id).addEventListener('input',()=>{settingsDirty=true;if($('frameExportMode').value==='all')$('autoFps').value=$('videoFps').value;$('autoFps').disabled=$('frameExportMode').value!=='sampled'});
$('disableAutomatic').onclick=()=>action('/api/automatic/disable');
$('testAudio').onclick=async()=>{const result=await action('/api/audio/test',{output:$('audioOutput').value});if(result)notice(result.message)};
$('uploadTone').onclick=async()=>{const file=$('toneFile').files[0];if(!file){notice('Choose your CE5 audio file first.');return}if(file.size>100*1024**2){notice('Choose an audio file smaller than 100 MB.');return}if(busy)return;busy=true;$('uploadTone').disabled=true;try{const response=await fetch('/api/tone',{method:'POST',headers:{'X-Station-Token':state.csrf,'X-Audio-Name':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'},body:file});const data=await response.json();if(!response.ok)throw Error(data.error);notice('CE5 audio uploaded and prepared.');await refresh()}catch(e){notice(e.message)}finally{busy=false;$('uploadTone').disabled=false}};
$('retryFrames').onclick=()=>action('/api/frames/retry',{id:selected.id});
$('mark').onclick=async()=>{if(await action('/api/mark',{note:$('markerNote').value}))$('markerNote').value=''};
$('closeReview').onclick=()=>{$('player').pause();$('review').close()};
$('review').addEventListener('close',()=>$('player').pause());
$('receiver').href=`http://${location.hostname}:8073/`;
function automation(title,detail,status,good){const row=el('div',undefined,'action');row.append(el('span',undefined,'dot'+(good?'':' warn')));const info=el('div',title);info.append(el('small',detail));row.append(info,el('b',status));return row}
function draw(frame,fresh,target='spectrum'){const c=$(target),ratio=devicePixelRatio||1;c.width=c.clientWidth*ratio;c.height=180*ratio;const x=c.getContext('2d');x.scale(ratio,ratio);const w=c.clientWidth,h=180;x.clearRect(0,0,w,h);x.strokeStyle='#25343b';x.lineWidth=1;for(let y=10;y<h;y+=40){x.beginPath();x.moveTo(0,y);x.lineTo(w,y);x.stroke()}const a=frame.average_db||[];const values=a.filter(Number.isFinite);if(!values.length||!fresh){x.fillStyle='#93a6ab';x.font='12px system-ui';x.fillText('Waiting for fresh RF measurements',20,85);return}const min=Math.floor(Math.min(...values)/10)*10-5,max=Math.max(min+30,Math.ceil(Math.max(...values)/10)*10+5);x.beginPath();a.forEach((v,i)=>{if(!Number.isFinite(v))return;const px=i/(a.length-1)*w,py=h-10-(v-min)/(max-min)*(h-25);i?x.lineTo(px,py):x.moveTo(px,py)});x.strokeStyle='#b4ed91';x.lineWidth=1.5;x.stroke();x.lineTo(w,h);x.lineTo(0,h);x.closePath();const g=x.createLinearGradient(0,0,0,h);g.addColorStop(0,'#b4ed9133');g.addColorStop(1,'#b4ed9100');x.fillStyle=g;x.fill();if(target==='spectrum')text('floor',`Noise floor ${frame.noise_floor_db??'—'} dB · relative`)}
function review(m){selected=m;renderReviewYouTube(m);$('reviewTitle').textContent=m.title;$('player').hidden=!m.files?.['video.mp4'];if(m.files?.['video.mp4'])$('player').src=`/sessions/${m.id}/video.mp4`;else $('player').removeAttribute('src');renderReviewArchive(m);$('reviewMeta').textContent=`${m.condition} · ${m.state}${m.trial_valid===false?' · INCOMPLETE TRIAL':''} · ${m.rf_records} RF snapshots · ${m.video||''} · ${m.video_playback?.state==='queued'?'Preparing playback and frames · ':''}${m.notes||'No notes'} · ${m.stop_reason||'Recording'} · ${m.timing}`;reviewMediaKey='';renderDownloads(m);$('markers').replaceChildren(...(m.markers||[]).map(marker=>{const row=el('div',undefined,'marker');const b=el('button',formatTime(marker.elapsed_seconds));b.onclick=()=>{if(!m.files?.['video.mp4']&&m.youtube?.url&&!m.internet_archive?.verified_at){const url=new URL(m.youtube.url);url.searchParams.set('t',Math.floor(marker.elapsed_seconds)+'s');window.open(url,'_blank','noopener');return}$('player').currentTime=marker.elapsed_seconds;$('player').play().catch(()=>{})};row.append(b,document.createTextNode(marker.note));return row}));$('review').showModal();frameKey='';showFrames(m);recorded=[];draw({},false,'recordedSpectrum');text('recordedTime','Loading recorded measurements…');if(m.files?.['rf.jsonl'])fetch(`/sessions/${m.id}/rf.jsonl`).then(r=>{if(!r.ok)throw Error('RF data unavailable');return r.text()}).then(t=>{if(selected.id!==m.id)return;recorded=t.trim().split('\n').filter(Boolean).map(l=>JSON.parse(l));recordedFrame()}).catch(e=>text('recordedTime',e.message));else text('recordedTime','No RF measurements were saved for this session.');}
function recordedFrame(){if(!recorded.length)return;const t=$('player').currentTime;let nearest=recorded[0];for(const r of recorded){if(Math.abs(r.elapsed_seconds-t)<Math.abs(nearest.elapsed_seconds-t))nearest=r;if(r.elapsed_seconds>t+2)break}draw(nearest.spectrum,true,'recordedSpectrum');text('recordedTime',`Nearest RF snapshot: ${nearest.elapsed_seconds.toFixed(1)} s · video: ${t.toFixed(1)} s · offset: ${(nearest.elapsed_seconds-t).toFixed(1)} s · ${nearest.captured_at}. HDMI latency is uncalibrated.`)}
$('player').addEventListener('timeupdate',recordedFrame);
function render(s){state=s;renderRecordingTags(s.active);text('connection','● STATION ONLINE');text('clock',new Date(s.now).toISOString().slice(0,19).replace('T',' ')+' UTC');text('cameraFormat',`Cam Link · 1080p / ${s.camera.capture_fps||s.experiments.automatic.video_fps||60} fps`);text('cameraStatus',s.camera.fresh?'Receiving frames':s.camera.connected?'No fresh frames':'Disconnected');text('rfStatus',s.rf.fresh?'Logging live':'Data stale');text('storage',s.storage.available===false?'Drive unavailable':(s.storage.free/1024**3).toFixed(1)+' GB free');$('storage').title=s.storage.path||'';text('sessionStatus',s.active?'Recording':'Standby');text('sessionDetail',s.active?`${s.active.rf_records} RF snapshots captured`:'Ready for an observation');$('captureForm').hidden=!!s.active||!!s.experiments?.automatic.enabled;$('manualBusy').hidden=!s.experiments?.automatic.enabled||!!s.active;$('activeControls').hidden=!s.active;
 if(s.active){text('activeTitle',s.active.title);text('elapsed',formatTime(Math.max(0,Date.now()/1000-s.active.started_epoch)));text('activeMeta',`${s.active.capture_origin==='rf_trigger'?'RF-triggered':s.active.condition} · limit ${formatTime(s.active.duration_limit_seconds)}`);text('markerCount',`${s.active.markers.length} timestamped markers${s.active.capture_mode==='motion_window'?' · Saves through '+Math.ceil(s.active.motion_tail_remaining_seconds||0)+' s after latest motion':''}`)}
 text('rfDetail',s.rf.fresh?`${(s.rf.frame.detections||[]).length} threshold detections in latest snapshot · source age ${s.rf.age_seconds.toFixed(1)} s · no raw IQ`:'RF snapshots are missing or stale. Check OpenWebRX and the logger.');draw(s.rf.frame,s.rf.fresh);
 const services=s.services,logger=services['hackrf-signal-logger.service']||{},timer=services['hackrf-signal-publish.timer']||{},pub=services['hackrf-signal-publish.service']||{},receiver=services['openwebrx.service']||{};
 $('automations').replaceChildren(automation('Continuous RF logging',s.rf.fresh?'Fresh one-second spectrum snapshots':'No fresh RF data',logger.ActiveState||'checking',s.rf.fresh&&logger.ActiveState==='active'),automation('Hourly RF archive upload',timer.NextElapseUSecRealtime?`Next: ${timer.NextElapseUSecRealtime}`:'Next run unavailable',timer.ActiveState||'checking',timer.ActiveState==='active'),automation('Last upload result',pub.ExecMainExitTimestamp||'No completed run reported',pub.Result||'unknown',pub.Result==='success'),automation('OpenWebRX receiver','Owns the HackRF; dashboard reads existing data',receiver.ActiveState||'checking',receiver.ActiveState==='active'),automation('Session safeguards','Duration limit + 2 GB free-space reserve',s.active?'armed':'ready',true),automation('Clock synchronization','UTC timestamps; camera latency uncalibrated',services.clock==='yes'?'synchronized':'check clock',services.clock==='yes'),automation('SSD and RF recovery',services['field-station-recovery.timer']?.ActiveState==='active'?'Retries missing SSD and failed services every minute':'System recovery installer required',services['field-station-recovery.timer']?.ActiveState==='active'?'enabled':'setup needed',services['field-station-recovery.timer']?.ActiveState==='active'),automation('Dashboard after reboot',services.autostart_linger==='yes'?'User service can start without login':'Starts with user login; lingering is disabled',services.autostart_linger==='yes'?'enabled':'login needed',services.autostart_linger==='yes'));
 text('journal',s.upload_journal||'No journal entries available.');text('sessionCount',`${s.sessions.length} session${s.sessions.length===1?'':'s'}`);
 const key=JSON.stringify(s.sessions.map(m=>[m.id,m.state,m.rf_records,m.files,m.frames,m.youtube,m.internet_archive]));if(key!==libraryKey){libraryKey=key;if(s.sessions.length)$('sessions').replaceChildren(...s.sessions.map(m=>{const row=el('div',undefined,'session-row');const info=el('div');info.append(el('strong',m.title),el('small',`${new Date(m.started_at).toLocaleString()} · ${m.condition} · ${m.rf_records} RF snapshots${m.internet_archive?' · Archive '+m.internet_archive.state.replaceAll('_',' '):''}${m.youtube?' · YouTube '+m.youtube.state.replaceAll('_',' '):''}${m.trial_valid===false?' · INCOMPLETE TRIAL':''} · ${m.frames?.state==='completed'?m.frames.count+' frames':m.frames?.state?'frames '+m.frames.state:'frames not exported'}`));const b=el('button',m.state==='recording'?'Recording…':'Review session');b.disabled=m.state==='recording';b.onclick=()=>review(m);row.append(info,el('span',m.state.toUpperCase()),b);if(m.youtube?.url){const link=el('a','YouTube ↗');link.href=m.youtube.url;link.target='_blank';link.rel='noopener';row.append(link)}if(m.internet_archive?.verified_at){const link=el('a','Internet Archive ↗');link.href=m.internet_archive.url;link.target='_blank';link.rel='noopener';row.append(link)}return row}))}
 if(s.youtube_live){const live=s.youtube_live;text('liveTestPhase',(live.phase||'waiting').replaceAll('_',' ').toUpperCase());text('liveTestStatus',live.error||'M1 remote encoder · 720p · unlisted 10-minute test');$('liveTestWatch').hidden=!live.watch_url;if(live.watch_url)$('liveTestWatch').href=live.watch_url;}renderExperiments(s.experiments);renderRFTrigger(s.rf_trigger);renderMotion(s.motion_trigger);text('bufferStatus',s.rolling_buffer?`RAM buffer: ${s.rolling_buffer.available_seconds.toFixed(1)} seconds available · ${(s.rolling_buffer.bytes/1024**2).toFixed(0)} MiB · ${s.rolling_buffer.error||'native video; idle footage expires automatically'}`:'Buffer status unavailable');renderMotionEvents(s);renderArchive(s.internet_archive);renderYouTube({...s.youtube,preparation_paused:s.experiments?.exports_paused});if(s.stills?.error)text('youtubeError','Stills archive: '+s.stills.error);if($('review').open&&selected){const updated=s.sessions.find(m=>m.id===selected.id);if(updated){selected=updated;renderReviewYouTube(updated);renderReviewArchive(updated);renderDownloads(updated);if(updated.files?.['video.mp4']&&!$('player').getAttribute('src')){$('player').src=`/sessions/${updated.id}/video.mp4`;$('player').hidden=false}showFrames(updated)}}
 if(!s.camera.fresh&&!previewHasFrame)text('noVideo',s.camera.connected?'Camera connected; waiting for frames.':'Connect the Cam Link to the Pi.');
}
async function refresh(){try{const r=await fetch('/api/status');if(!r.ok)throw Error('Status unavailable');render(await r.json())}catch(e){text('connection','STATION OFFLINE');renderRecordingTags(null,true);notice('Dashboard connection lost. Capture state is unknown; reconnect before starting another session.')}}
let previewRetry,previewController,previewGeneration=0,previewHasFrame=false;
let previewLastFrame=0,previewFrames=0,previewFailures=0,previewUseSnapshots=false;
function decodePreviewFrame(frame){
 return new Promise((resolve,reject)=>{
  const url=URL.createObjectURL(new Blob([frame],{type:'image/jpeg'}));
  const image=new Image();
  image.onload=()=>{URL.revokeObjectURL(url);resolve(image)};
  image.onerror=()=>{URL.revokeObjectURL(url);reject(Error('Camera frame could not be decoded'))};
  image.src=url;
 });
}
function drawPreviewFrame(image){
 const canvas=$('preview');
 if(canvas.width!==image.naturalWidth||canvas.height!==image.naturalHeight){canvas.width=image.naturalWidth;canvas.height=image.naturalHeight}
 canvas.getContext('2d').drawImage(image,0,0);
 previewHasFrame=true;previewLastFrame=Date.now();previewFrames++;
 canvas.hidden=false;$('noVideo').hidden=true;
}
async function previewSnapshots(controller,generation,fps){
 let measured=performance.now(),count=0;
 while(generation===previewGeneration&&!controller.signal.aborted){
  const started=performance.now();
  const timeout=setTimeout(()=>controller.abort(),8000);
  try{
   const response=await fetch('/preview.jpg?t='+Date.now(),{signal:controller.signal,cache:'no-store'});
   if(!response.ok)throw Error('Camera frame unavailable');
   const image=await decodePreviewFrame(await response.arrayBuffer());
   if(generation!==previewGeneration||controller.signal.aborted)return;
   drawPreviewFrame(image);count++;
   if(!$('previewLabel').textContent.startsWith('LIVE'))text('previewLabel','LIVE');
   if(performance.now()-measured>=1000){text('previewLabel',`LIVE · ${Math.round(count*1000/(performance.now()-measured))} FPS`);count=0;measured=performance.now()}
  }finally{clearTimeout(timeout)}
  await new Promise(resolve=>setTimeout(resolve,Math.max(0,1000/Number(fps)-(performance.now()-started))));
 }
}
$('preview').hidden=true;
async function startPreview(){
 clearTimeout(previewRetry);
 const generation=++previewGeneration;
 if(previewController)previewController.abort();
 if(document.hidden)return;
 const controller=new AbortController();previewController=controller;
 const fps=$('previewFps').value;
 text('previewLabel',previewHasFrame?'RECONNECTING…':'CONNECTING…');
 let reader,watchdog,lastGood=performance.now(),buffer=new Uint8Array(0),frameLength=null;
 if(previewUseSnapshots){
  try{await previewSnapshots(controller,generation,fps)}catch(error){if(generation===previewGeneration&&!document.hidden)text('previewLabel','WAITING FOR CAMERA…')}
  finally{controller.abort();if(generation===previewGeneration&&!document.hidden)previewRetry=setTimeout(startPreview,1000)}
  return;
 }
 watchdog=setInterval(()=>{if(performance.now()-lastGood>5000)controller.abort()},1000);
 try{
  const response=await fetch('/preview.mjpeg?fps='+fps+'&t='+Date.now(),{signal:controller.signal,cache:'no-store'});
  if(!response.ok||!response.body)throw Error('Camera stream unavailable');
  reader=response.body.getReader();
  while(generation===previewGeneration){
   const {value,done}=await reader.read();
   if(done)throw Error('Camera stream ended');
   const combined=new Uint8Array(buffer.length+value.length);combined.set(buffer);combined.set(value,buffer.length);buffer=combined;
   if(buffer.length>16*1024*1024)throw Error('Invalid camera frame');
   while(true){
    if(frameLength===null){
     let end=-1;
     for(let i=0;i+3<buffer.length;i++)if(buffer[i]===13&&buffer[i+1]===10&&buffer[i+2]===13&&buffer[i+3]===10){end=i;break}
     if(end<0)break;
     const header=new TextDecoder().decode(buffer.subarray(0,end));
     const match=header.match(/Content-Length:\s*(\d+)/i);
     if(!match)throw Error('Invalid camera stream');
     frameLength=Number(match[1]);
     if(frameLength<4||frameLength>16*1024*1024)throw Error('Invalid camera frame size');
     buffer=buffer.slice(end+4);
    }
    if(buffer.length<frameLength)break;
    const frame=buffer.slice(0,frameLength);buffer=buffer.slice(frameLength);frameLength=null;
    let image;
    try{
     image=await decodePreviewFrame(frame);
     if(generation!==previewGeneration||controller.signal.aborted)break;
     drawPreviewFrame(image);lastGood=performance.now();
     text('previewLabel',`LIVE · ${fps} FPS`);
    }catch(error){
     // Ignore a damaged camera packet and retain the last decoded picture.
    }
   }
  }
 }catch(error){
  if(generation===previewGeneration&&!document.hidden){previewFailures++;if(previewFailures>=2)previewUseSnapshots=true;$('previewLabel').title=error.message;text('previewLabel','RECONNECTING…');if(!previewHasFrame){$('noVideo').hidden=false;text('noVideo','Connecting to live camera…')}}
 }finally{
  clearInterval(watchdog);
  if(reader)try{await reader.cancel()}catch(error){}
  controller.abort();
  if(generation===previewGeneration&&!document.hidden)previewRetry=setTimeout(startPreview,1000);
 }
}
$('previewFps').onchange=()=>{previewFailures=0;previewUseSnapshots=false;startPreview()};
document.addEventListener('visibilitychange',startPreview);
refresh();setInterval(refresh,2000);startPreview();

function renderExperiments(e){
 if(!e)return;
 const a=e.automatic;
 if(e.tone.library_path&&!$('toneLibrary').value&&Array.from($('toneLibrary').options).some(o=>o.value===e.tone.library_path))$('toneLibrary').value=e.tone.library_path;
 text('automaticPhase',a.phase.replaceAll('_',' ').toUpperCase());
 text('toneStatus',e.tone.ready?`Ready: ${e.tone.name} · ${e.tone.preparation}`:'Upload the CE5 audio you want to play.');
 const due=a.next_condition==='ce5'?a.next_session_epoch:a.next_cycle_epoch;
 text('automaticDetail',a.enabled?`${a.completed_sessions} sessions saved · next ${a.next_condition}: ${due?new Date(due*1000).toLocaleString():'pending'} · settings apply to next cycle.`:'Enabled schedules resume after restart. An interrupted cycle is skipped; the next scheduled cycle starts with silence.');
 text('scheduleSummary',`${a.duration_minutes} min recording · every ${a.interval_minutes} min · ${a.gap_minutes} min minimum gap · ${a.video_fps} fps video · ${a.frame_export_mode==='selected'?'up to 3 selected original stills':a.frame_export_mode==='all'?'EVERY recorded frame exported':a.frame_fps+' JPEGs/sec (sampled)'}. ${a.ce5_enabled?'Silence + CE5 per cycle.':'Silent captures only; CE5 playback is off until a speaker is configured.'}`);
 text('automaticError',a.error||'');
 $('enableAutomatic').hidden=a.enabled;$('disableAutomatic').hidden=!a.enabled;
 $('enableAutomatic').disabled=busy||($('ce5Enabled').checked&&(!e.tone.ready||!e.outputs.length));
 const key=JSON.stringify(e.outputs);
 if(key!==audioKey){audioKey=key;const previous=$('audioOutput').value;$('audioOutput').replaceChildren(el('option','Select a Pi playback device'));$('audioOutput').firstChild.value='';for(const output of e.outputs){const option=el('option',output.name);option.value=output.id;$('audioOutput').append(option)}$('audioOutput').value=previous||a.output||''}
 if(!settingsDirty&&settingsRevision!==a.settings_revision){
  $('autoDuration').value=a.duration_minutes;$('autoGap').value=a.gap_minutes;$('autoInterval').value=a.interval_minutes;$('autoFps').value=a.frame_fps;$('videoFps').value=a.video_fps;$('frameExportMode').value=a.frame_export_mode;
  $('ce5Enabled').checked=a.ce5_enabled;$('toneVolume').value=Math.round(a.volume*100);$('audioOutput').value=a.output||'';$('automaticRepeat').value=a.repeat?'repeat':'once';settingsRevision=a.settings_revision;
 }
 $('toneLibrary').disabled=a.enabled||!!state.active;$('selectLibraryTone').disabled=busy||a.enabled||!!state.active;
 $('audioOutput').disabled=busy;$('toneVolume').disabled=busy;$('uploadTone').disabled=busy||a.enabled||!!state.active;
 $('autoFps').disabled=$('frameExportMode').value!=='sampled';$('testAudio').disabled=busy||a.enabled||!!state.active;$('saveAutomaticSettings').disabled=busy;
}

function renderFramePage(){
 const start=galleryPage*120, end=Math.min(start+120,galleryFrames.length), sid=selected.id;
 $('frameGallery').replaceChildren(...galleryFrames.slice(start,end).map((frame,offset)=>{const a=el('a',`#${start+offset+1} · ${frame.video_time_seconds.toFixed(3)} s`);a.href=`/sessions/${sid}/frames/${frame.file}`;a.target='_blank';a.rel='noopener';const img=el('img');img.src=a.href;img.loading='lazy';img.alt=`Frame ${start+offset+1} at ${frame.video_time_seconds} seconds`;a.prepend(img);return a}));
 text('framePageLabel',galleryFrames.length?`${start+1}–${end} / ${galleryFrames.length}`:'No frames');$('previousFramePage').disabled=galleryPage===0;$('nextFramePage').disabled=end>=galleryFrames.length;
}
$('previousFramePage').onclick=()=>{if(galleryPage>0){galleryPage--;renderFramePage()}};
$('nextFramePage').onclick=()=>{if((galleryPage+1)*120<galleryFrames.length){galleryPage++;renderFramePage()}};
function showFrames(m){
 const key=m.id+JSON.stringify(m.frames);if(key===frameKey)return;frameKey=key;galleryFrames=[];galleryPage=0;renderFramePage();
 $('retryFrames').hidden=m.state!=='completed'||['queued','processing','completed'].includes(m.frames?.state);
 text('frameStatus',m.frames?.state==='completed'?`${m.frames.count} full-resolution JPEG frames · ${m.frames.mode==='selected'?'selected original stills':m.frames.mode==='all'?'EVERY recorded frame':m.frames.fps+' per second (sampled)'}. Open a frame to view or save it.`:`Frame export: ${m.frames?.state||'not yet requested'}${m.frames?.error?' · '+m.frames.error:''}`);
 if(m.frames?.state!=='completed')return;const sid=m.id;fetch(`/sessions/${sid}/frames/index.json`).then(r=>{if(!r.ok)throw Error('Frame index unavailable');return r.json()}).then(index=>{if(selected.id!==sid)return;galleryFrames=index.frames;galleryPage=0;renderFramePage()}).catch(e=>text('frameStatus',e.message));
}

async function refreshToneLibrary(){try{const response=await fetch('/api/tone/library');if(!response.ok)throw Error('Audio library unavailable');const tracks=await response.json();const current=$('toneLibrary').value;$('toneLibrary').replaceChildren();const placeholder=el('option',tracks.length?'Select a track on the T7':'No audio in T7/Uploads');placeholder.value='';$('toneLibrary').append(placeholder);for(const track of tracks){const option=el('option',track.name);option.value=track.path;$('toneLibrary').append(option)}$('toneLibrary').value=current||state?.experiments?.tone?.library_path||''}catch(e){notice(e.message)}}
$('refreshToneLibrary').onclick=refreshToneLibrary;
$('selectLibraryTone').onclick=async()=>{const path=$('toneLibrary').value;if(!path){notice('Select a track from the SSD library.');return}const result=await action('/api/tone/select',{path});if(result)notice('Prepared the selected track. The original uploaded track is unchanged.')};
refreshToneLibrary();

function rfValues(){return {threshold_db:10*Math.log10(Number($('rfPowerRatio').value)),temporal_threshold_db:10*Math.log10(Number($('rfBaselineRatio').value)),broadband_rise_db:10*Math.log10(Number($('rfFloorRatio').value)),confirm_snapshots:Number($('rfConfirm').value),duration_minutes:Number($('rfDuration').value),cooldown_minutes:Number($('rfCooldown').value),baseline_samples:Number($('rfWarmup').value),baseline_window:Number($('rfWindow').value),min_bandwidth_khz:Number($('rfWidth').value),broadband_fraction:Number($('rfCoverage').value)/100,hysteresis_db:Number($('rfHysteresis').value),quiet_snapshots:Number($('rfQuiet').value),max_delay_seconds:Number($('rfMaxDelay').value)}}
for(const id of ['rfPowerRatio','rfBaselineRatio','rfFloorRatio','rfConfirm','rfDuration','rfCooldown','rfWarmup','rfWindow','rfWidth','rfCoverage','rfHysteresis','rfQuiet','rfMaxDelay'])$(id).addEventListener('input',()=>{rfDirty=true});
$('rfSave').onclick=async()=>{const result=await action('/api/rf-trigger/configure',{...rfValues(),enabled:state.rf_trigger.enabled});if(result){rfDirty=false;rfSettingsKey='';renderRFTrigger(state.rf_trigger);notice('RF trigger settings saved.')}};
$('rfToggle').onclick=async()=>{const result=await action('/api/rf-trigger/configure',{...rfValues(),enabled:!state.rf_trigger.enabled});if(result){rfDirty=false;rfSettingsKey='';renderRFTrigger(state.rf_trigger)}};
function renderRFTrigger(r){if(!r)return;text('rfTriggerPhase',r.phase.replaceAll('_',' ').toUpperCase());text('rfToggle',r.enabled?'Disable RF trigger':'Enable RF trigger');$('rfToggle').className=r.enabled?'danger':'primary';text('rfTriggerStatus',`${r.baseline_ready?'Baseline ready':'Learning baseline'}: ${r.baseline_samples_collected}/${r.baseline_samples} minimum fresh snapshots · latest peak ${r.latest_peak_db===null?'—':r.latest_peak_db.toFixed(1)+' dB above floor'} · ${r.consecutive}/${r.confirm_snapshots} confirmations`);text('rfTriggerError',r.error||'');const e=r.last_event;text('rfLastEvent',e?`Last RF event: ${e.detected_at} · ${e.detection.kind} · ${e.action} · ${e.session_id||'no recording yet'}`:'No confirmed RF events yet.');const fields=['threshold_db','temporal_threshold_db','broadband_rise_db','confirm_snapshots','duration_minutes','cooldown_minutes','baseline_samples','baseline_window','min_bandwidth_khz','broadband_fraction','hysteresis_db','quiet_snapshots','max_delay_seconds'];const key=JSON.stringify(fields.map(k=>r[k]));if(!rfDirty&&key!==rfSettingsKey){rfSettingsKey=key;for(const [id,key]of [['rfConfirm','confirm_snapshots'],['rfDuration','duration_minutes'],['rfCooldown','cooldown_minutes'],['rfWarmup','baseline_samples'],['rfWindow','baseline_window'],['rfWidth','min_bandwidth_khz'],['rfHysteresis','hysteresis_db'],['rfQuiet','quiet_snapshots'],['rfMaxDelay','max_delay_seconds']])$(id).value=r[key];$('rfCoverage').value=r.broadband_fraction*100;$('rfPowerRatio').value=Number(Math.pow(10,r.threshold_db/10).toFixed(2));$('rfBaselineRatio').value=Number(Math.pow(10,r.temporal_threshold_db/10).toFixed(2));$('rfFloorRatio').value=Number(Math.pow(10,r.broadband_rise_db/10).toFixed(2));}}

let motionDirty=false,motionKey="",motionProfileDirty=false;
$('motionFilterProfile').onchange=()=>{motionProfileDirty=true};
$('motionApplyProfile').onclick=async()=>{
 const profile=$('motionFilterProfile').value;if(profile==='custom')return;
 if(await action('/api/motion-trigger/configure',{filter_profile:profile})){
  motionProfileDirty=false;motionDirty=false;motionKey='';renderMotion(state.motion_trigger);notice('Motion filter preset applied.');
 }
};
const motionFields=['analysis_width', 'pre_roll_seconds', 'post_roll_seconds', 'cooldown_minutes', 'min_area_percent', 'pixel_threshold', 'confirmation_seconds', 'analysis_fps', 'max_area_percent', 'reference_seconds'];
for(const key of motionFields) $('motion_'+key).oninput=()=>{motionDirty=true};
$('motionCloudSuppression').onchange=()=>{motionDirty=true};
function motionValues(){return {...Object.fromEntries(motionFields.map(k=>[k,Number($('motion_'+k).value)])),cloud_suppression:$('motionCloudSuppression').checked}}
$('motionSave').onclick=async()=>{if(await action('/api/motion-trigger/configure',{...motionValues(),enabled:state.motion_trigger.enabled})){motionDirty=false;motionKey='';renderMotion(state.motion_trigger);notice('Motion settings saved.')}};
$('motionToggle').onclick=async()=>{if(await action('/api/motion-trigger/configure',{...motionValues(),enabled:!state.motion_trigger.enabled})){motionDirty=false;motionKey='';renderMotion(state.motion_trigger)}};
function renderMotion(m){if(!m)return;const profile=m.filter_profile||'custom';if(!motionProfileDirty&&document.activeElement!==$('motionFilterProfile'))$('motionFilterProfile').value=profile;text('motionProfileStatus',`Active: ${profile} · Select presets manually. Nighttime keeps noise filtering and compares over a longer interval.`);renderRegionOverlay(m);text('motionPhase',m.phase.replaceAll('_',' ').toUpperCase());text('motionToggle',m.enabled?'Disable motion trigger':'Enable motion trigger');$('motionToggle').className=m.enabled?'danger':'primary';text('motionStatus',`${m.changed_area_percent.toFixed(4)}% changed · trigger minimum ${m.min_area_percent}% · ${m.actual_analysis_fps} analysis fps / ${m.analysis_fps} requested · ${m.analysis_width} px analysis width${m.cloud_suppression?' · Cloud suppression on':''}`);text('motionError',m.error||'');const e=m.last_event;text('motionLast',e?`Last motion: ${e.detected_at} · ${e.action} · ${e.session_id||'no recording'}`:'No confirmed motion events yet.');const key=JSON.stringify([...motionFields.map(k=>m[k]),m.cloud_suppression]);if(!motionDirty&&key!==motionKey){motionKey=key;for(const k of motionFields)$('motion_'+k).value=m[k];$('motionCloudSuppression').checked=!!m.cloud_suppression}}

function renderRecordingTags(active,unknown=false){
 const labels=[];
 if(unknown)labels.push(['STATUS UNKNOWN','unknown']);
 else if(!active)labels.push(['STANDBY · NOT RECORDING','standby']);
 else {
  if(active.capture_origin==='scheduled')labels.push(['● SCHEDULED RECORDING','scheduled']);
  if(active.capture_origin==='motion_trigger'||active.motion_events?.length)labels.push(['● MOTION RECORDING','motion']);
  if(active.capture_origin==='rf_trigger'||active.rf_trigger_events?.length)labels.push(['● RF-TRIGGERED RECORDING','rf']);
  if(!labels.length)labels.push(['● MANUAL RECORDING','manual']);
 }
 const key=JSON.stringify(labels),container=$('recordingTags');
 container.classList.toggle('recording-active',!!active&&!unknown);
 if(container.dataset.status===key)return;
 container.dataset.status=key;
 container.replaceChildren(...labels.map(([label,type])=>el('span',label,'recording-tag '+type)));
}

let motionEventKey='',motionEventOptions='',motionShowAll=false;
$('motionEventSession').onchange=()=>{motionEventKey='';motionShowAll=false;renderMotionEvents(state)};
$('motionEventsMore').onclick=()=>{motionShowAll=!motionShowAll;motionEventKey='';renderMotionEvents(state)};
function renderMotionEvents(s){const analysis=s.object_analysis;text('objectAnalysisStatus',analysis?`Shape + object labels · recordings retained · ${analysis.queued} queued${analysis.processing?' · analyzing':''}${analysis.error?' · '+analysis.error:''}`:'Shape + object labels loading…');
 const sessions=[...(s.active?[s.active]:[]),...s.sessions.filter(m=>m.id!==s.active?.id)].filter(m=>m.motion_events?.length);
 const options=JSON.stringify(sessions.map(m=>[m.id,m.state]));const selector=$('motionEventSession');
 if(options!==motionEventOptions){motionEventOptions=options;const selected=selector.value;selector.replaceChildren(new Option('Current / latest motion session',''),...sessions.map(m=>new Option(`${m.state==='recording'?'Recording · ':''}${new Date(m.started_at).toLocaleString()} · ${m.id}`,m.id)));if(sessions.some(m=>m.id===selected))selector.value=selected}
 const session=sessions.find(m=>m.id===selector.value)||sessions[0];const events=session?.motion_events||[];
 text('motionEventCount',`${events.length} EVENTS`);text('motionEventDetail',session?`${session.state==='recording'?'Recording now':'Saved session'} · ${session.id} · ${events.length} motion triggers saved`:'No saved motion triggers yet.');
 const key=JSON.stringify([session?.id,events.length,events.map(e=>[e.id,e.annotation?.annotation_version,e.annotation?.source_frame,e.classification?.classified_at,e.classification?.state,e.human_review?.reviewed_at]),motionShowAll]);if(key===motionEventKey)return;motionEventKey=key;
 const visible=motionShowAll?events:events.slice(-20);$('motionEventList').replaceChildren(...visible.slice().reverse().map(e=>{
  const row=el('article',undefined,'motion-event');row.append(el('strong',`${new Date(e.detected_at).toLocaleTimeString()} · +${formatTime(Math.max(0,e.detected_epoch-session.started_epoch))}`));
  row.append(el('p',`${Number(e.changed_area_percent).toFixed(4)}% changed · ${(e.action||'confirmed').replaceAll('_',' ')}`,'caption'));
  const classification=e.human_review?{state:'completed',regions:e.human_review.regions.map(r=>({object:{label:r.object,reviewed:true},shape:{label:r.shape}}))}:e.classification;
  if(classification?.state==='completed'){
   for(const [i,region]of classification.regions.entries()){
    const object=region.object,shape=region.shape;
    row.append(el('p',`Target ${i+1}: ${object.reviewed?object.label.replaceAll('_',' ')+' (reviewed)':object.label==='unknown'?'unknown':'likely '+object.label.replaceAll('_',' ')}${object.confidence?' · model score '+Math.round(object.confidence*100)+'%':''}${object.support_frames===1?' · single-frame suggestion':''} · shape: ${shape.label.replaceAll('_',' ')}${shape.width_pixels?' ('+shape.width_pixels+' × '+shape.height_pixels+' px)':''}`,'classification-label'));
   }
   if(!classification.regions.length)row.append(el('p','Unknown · no separable target region','caption'));
   if(classification.error)row.append(el('p','Object recognition unavailable: '+classification.error,'caption'));
  }else row.append(el('p',classification?.state==='queued'?'Shape / object analysis queued':'Shape / object labels not analyzed','caption'));
  if(classification?.state!=='queued'){
   const classify=el('button',classification?.state==='completed'?'Recheck shape + object':'Analyze shape + object');
   classify.onclick=async()=>{if(await action('/api/motion/classify',{session_id:session.id,event_id:e.id}))notice('Shape and object analysis queued.');};row.append(classify);
  }
  const links=el('div',undefined,'motion-event-links');
  const files=[e.annotated_frame,...(e.evidence_files||[])].filter(Boolean);
  for(const file of [...new Set(files)]){if(!/^motion-[a-f0-9]{16}-(before|after|boxed)\.jpg$/.test(file))continue;const a=el('a',file.endsWith('-boxed.jpg')?('Motion evidence · '+(e.annotation?.source_frame==='before'?'earlier frame':'later frame')):file.endsWith('-after.jpg')?'Original trigger frame':'Comparison frame');a.href=`/sessions/${session.id}/${file}`+(file.endsWith('-boxed.jpg')?'?v='+(e.human_review?.reviewed_at||e.classification?.classified_at||e.annotation?.annotation_version||1):'');a.target='_blank';a.rel='noopener';links.append(a)}
  row.append(links);
  if(!e.annotated_frame||e.annotation?.annotation_version!==3){const b=el('button',e.annotated_frame?'Refresh motion evidence':'Annotate motion evidence');b.onclick=async()=>{motionEventKey='';if(await action('/api/motion/annotate',{session_id:session.id,event_id:e.id})){motionEventKey='';renderMotionEvents(state)}};row.append(b)}
  if(e.annotated_frame&&/^motion-[a-f0-9]{16}-boxed\.jpg$/.test(e.annotated_frame)){const details=el('details');details.append(el('summary','Show motion evidence · '+(e.annotation?.source_frame==='before'?'earlier frame':'later frame')));const a=el('a');a.href=`/sessions/${session.id}/${e.annotated_frame}?v=${e.human_review?.reviewed_at||e.classification?.classified_at||e.annotation?.annotation_version||1}`;a.target='_blank';a.rel='noopener';const img=el('img');img.dataset.src=a.href;details.ontoggle=()=>{if(details.open&&!img.getAttribute('src'))img.src=img.dataset.src};img.loading='lazy';img.alt='Motion evidence with changed regions on the '+(e.annotation?.source_frame==='before'?'earlier':'later')+' frame';a.append(img);details.append(a);row.append(details)}
  return row;
 }));$('motionEventsMore').hidden=events.length<=20;text('motionEventsMore',motionShowAll?'Show latest 20 events':`Show all ${events.length} events`);
}

const cameraViewfinder=$('cameraViewfinder'),fullscreenButton=$('previewFullscreen');
function cameraIsExpanded(){return document.fullscreenElement===cameraViewfinder||cameraViewfinder.classList.contains('preview-expanded')}
function syncCameraFullscreen(){const expanded=cameraIsExpanded();resetCameraChrome();fullscreenButton.textContent=expanded?'✕ Exit full screen':'⛶ Full screen';fullscreenButton.setAttribute('aria-pressed',String(expanded));fullscreenButton.setAttribute('aria-label',expanded?'Exit camera full screen':'Show camera preview full screen')}
let cameraChromeTimer;
function resetCameraChrome(){
 clearTimeout(cameraChromeTimer);
 cameraViewfinder.classList.remove('chrome-idle');
 if(cameraIsExpanded())cameraChromeTimer=setTimeout(()=>{
  if(cameraIsExpanded())cameraViewfinder.classList.add('chrome-idle');
 },5000);
}
for(const event of ['pointermove','pointerdown','keydown'])cameraViewfinder.addEventListener(event,resetCameraChrome);
function setCameraFallback(expanded){cameraViewfinder.classList.toggle('preview-expanded',expanded);document.body.classList.toggle('preview-expanded',expanded);syncCameraFullscreen();if(!expanded)fullscreenButton.focus()}
async function toggleCameraFullscreen(){
 if(document.fullscreenElement===cameraViewfinder){await document.exitFullscreen();return}
 if(cameraViewfinder.classList.contains('preview-expanded')){setCameraFallback(false);return}
 if(cameraViewfinder.requestFullscreen){try{await cameraViewfinder.requestFullscreen();syncCameraFullscreen();return}catch(e){/* HTTP and some iPads require the viewport fallback. */}}
 setCameraFallback(true);
}
fullscreenButton.addEventListener('click',()=>{toggleCameraFullscreen().catch(()=>setCameraFallback(false))});
document.addEventListener('fullscreenchange',syncCameraFullscreen);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&cameraViewfinder.classList.contains('preview-expanded')){event.preventDefault();setCameraFallback(false)}});

let regionEditing=false,regionDraft=[],regionSelected=-1,regionDragging=null,regionError='';
const regionCanvas=$('regionCanvas');
function savedRegion(m){return (m.roi_polygon||[[m.roi_left,m.roi_top],[m.roi_right,m.roi_top],[m.roi_right,m.roi_bottom],[m.roi_left,m.roi_bottom]]).map(p=>[...p])}
function svgElement(tag,attributes={}){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attributes))node.setAttribute(k,v);return node}
function renderRegionOverlay(m){
 $('regionInlineStatus').hidden=!regionEditing;text('regionInlineStatus',regionError||`${regionDraft.length} points · Tap to add; drag a point to move it.`);
 const overlay=$('motionRegion');overlay.hidden=!m.enabled&&!regionEditing;overlay.classList.toggle('region-editing',regionEditing);Object.assign(overlay.style,{left:'0',top:'0',width:'100%',height:'100%'});
 const points=regionEditing?regionDraft:savedRegion(m);const xy=points.map(([x,y])=>[x*10,y*5.625]);
 const outline=xy.map(p=>p.join(',')).join(' ');const nodes=[];
 if(regionEditing)nodes.push(svgElement('path',{d:'M0 0H1000V562.5H0Z M'+xy.map(p=>p.join(' ')).join(' L')+' Z','fill-rule':'evenodd',fill:'#0007'}));
 nodes.push(svgElement('polygon',{points:outline,fill:regionEditing?'#73f4d511':'none',stroke:'#76dec2','stroke-width':1.5,'stroke-dasharray':regionEditing?'none':'5 4','vector-effect':'non-scaling-stroke'}));
 if(regionEditing){const scale=1000/(regionCanvas.getBoundingClientRect().width||1000);xy.forEach(([x,y],i)=>{
  const group=svgElement('g',{'data-point':i});group.append(svgElement('circle',{cx:x,cy:y,r:18*scale,fill:'transparent'}),svgElement('circle',{cx:x,cy:y,r:6*scale,fill:i===regionSelected?'#ffcf33':'#90ffe0',stroke:'#082019','stroke-width':2,'vector-effect':'non-scaling-stroke'}));nodes.push(group);
 })}
 regionCanvas.replaceChildren(...nodes);
 $('regionEdit').hidden=regionEditing;
 for(const id of ['regionSave','regionCancel','regionRemove','regionReset'])$(id).hidden=!regionEditing;
 $('regionRemove').disabled=busy||regionSelected<0||regionDraft.length<=3;
 $('regionEdit').disabled=busy||!Object.prototype.hasOwnProperty.call(m,'roi_polygon');
 if(!regionEditing)text('regionEditStatus',`${points.length}-point detection border · Tap Edit border to add points and drag the boundary.`);
}
function regionChanged(){regionError='';renderRegionOverlay(state.motion_trigger);text('regionEditStatus',`Unsaved ${regionDraft.length}-point border${regionSelected>=0?' · point '+(regionSelected+1)+' selected':''}. Tap to add, drag to move, then Save border.`)}
$('regionEdit').onclick=()=>{if(!Object.prototype.hasOwnProperty.call(state.motion_trigger,'roi_polygon'))return;regionDraft=savedRegion(state.motion_trigger);regionSelected=-1;regionEditing=true;regionChanged();regionCanvas.focus()};
$('regionCancel').onclick=()=>{regionEditing=false;regionDragging=null;renderRegionOverlay(state.motion_trigger)};
$('regionReset').onclick=()=>{const m=state.motion_trigger;regionDraft=[[m.roi_left,m.roi_top],[m.roi_right,m.roi_top],[m.roi_right,m.roi_bottom],[m.roi_left,m.roi_bottom]];regionSelected=-1;regionChanged()};
$('regionRemove').onclick=()=>{if(regionSelected<0||regionDraft.length<=3)return;regionDraft.splice(regionSelected,1);regionSelected=-1;regionChanged()};
$('regionSave').onclick=async()=>{if(!regionEditing)return;const result=await action('/api/motion-trigger/configure',{roi_polygon:regionDraft});if(result){regionEditing=false;regionDragging=null;renderRegionOverlay(state.motion_trigger);notice('Detection border saved.')}else{regionError=$('notice').textContent||'Border not saved. Edges must not cross.';text('regionEditStatus',regionError);renderRegionOverlay(state.motion_trigger)}};
function regionPoint(event){const r=regionCanvas.getBoundingClientRect();return [Math.max(0,Math.min(100,(event.clientX-r.left)/r.width*100)),Math.max(0,Math.min(100,(event.clientY-r.top)/r.height*100))]}
function nearestRegionEdge(point){const r=regionCanvas.getBoundingClientRect();const p=[point[0]*r.width,point[1]*r.height];let best=Infinity,index=0;for(let i=0;i<regionDraft.length;i++){const a=[regionDraft[i][0]*r.width,regionDraft[i][1]*r.height],b=[regionDraft[(i+1)%regionDraft.length][0]*r.width,regionDraft[(i+1)%regionDraft.length][1]*r.height];const dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy||1)));const distance=(p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2;if(distance<best){best=distance;index=i}}return index}
regionCanvas.addEventListener('pointerdown',event=>{if(!regionEditing||busy||event.button>0)return;event.preventDefault();const handle=event.target.closest('[data-point]');if(handle)regionSelected=Number(handle.dataset.point);else{if(regionDraft.length>=32){text('regionEditStatus','Border limit: 32 points. Remove a point before adding another.');return}const point=regionPoint(event);regionSelected=nearestRegionEdge(point)+1;regionDraft.splice(regionSelected,0,point)}regionDragging=event.pointerId;try{regionCanvas.setPointerCapture(event.pointerId)}catch(e){}regionCanvas.focus();regionChanged()});
regionCanvas.addEventListener('pointermove',event=>{if(regionDragging!==event.pointerId||regionSelected<0)return;event.preventDefault();regionDraft[regionSelected]=regionPoint(event);regionChanged()});
for(const type of ['pointerup','pointercancel','lostpointercapture'])regionCanvas.addEventListener(type,()=>{regionDragging=null});
regionCanvas.addEventListener('keydown',event=>{if(!regionEditing)return;if(event.key==='Escape'){$('regionCancel').click();return}if(['Delete','Backspace'].includes(event.key)){event.preventDefault();$('regionRemove').click();return}if(regionSelected<0)return;const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];if(delta){event.preventDefault();regionDraft[regionSelected]=regionDraft[regionSelected].map((v,i)=>Math.max(0,Math.min(100,v+delta[i]*(event.shiftKey?1:.2))));regionChanged()}});
new ResizeObserver(()=>{if(state?.motion_trigger)renderRegionOverlay(state.motion_trigger)}).observe(regionCanvas);

let youtubeDirty=false,youtubeKey='';
for(const id of ['youtubePrivacy','youtubeLimit'])$(id).oninput=()=>{youtubeDirty=true};
$('youtubeSave').onclick=async()=>{if(await action('/api/youtube/configure',{privacy:$('youtubePrivacy').value,daily_upload_limit:Number($('youtubeLimit').value)})){youtubeDirty=false;youtubeKey='';renderYouTube(state.youtube)}};
$('youtubeToggle').onclick=()=>action('/api/youtube/configure',{enabled:!state.youtube.enabled});
$('youtubeImport').onclick=()=>action('/api/youtube/import');
$('youtubeConnect').onclick=()=>action('/api/youtube/connect');
$('preparePlayback').onclick=()=>action('/api/playback/prepare',{id:selected.id});
function renderYouTube(y){if(!y)return;text('youtubePhase',/exceeded the number of videos|uploadLimitExceeded/i.test(y.error||'')?'YOUTUBE UPLOAD LIMIT':y.phase.replaceAll('_',' ').toUpperCase());text('youtubeToggle',y.enabled?'Pause automatic uploads':'Enable automatic uploads');text('youtubeConnection',y.connected_channel?`Connected: ${y.connected_channel.title}${y.auth.refresh_expires_at?' · Google authorization expires '+new Date(y.auth.refresh_expires_at*1000).toLocaleDateString():''}`:y.auth.configured?'OAuth client configured; Google authorization required.':'OAuth credentials required.');const count=Object.entries({...y.counts,...y.preparation_counts}).map(([k,v])=>`${v} ${k.replaceAll('_',' ')}`).join(' · ');const progress=y.current?.total_bytes?` · ${y.current.id}: ${(y.current.uploaded_bytes/y.current.total_bytes*100).toFixed(0)}% uploaded`:'';text('youtubeStatus',(count||'No uploads queued yet.')+progress+(y.preparation_paused?' · Video preparation paused to limit disk use':'')+' · Originals retained for 1 hour after verification');text('youtubeError',y.error||y.auth.error||'');const pending=y.auth.user_code&&y.auth.expires_at>Date.now()/1000;text('youtubeAuthCode',pending?`Enter ${y.auth.user_code} at Google to authorize this channel.`:'');$('youtubeAuthLink').hidden=!pending;const key=JSON.stringify([y.privacy,y.daily_upload_limit]);if(!youtubeDirty&&key!==youtubeKey){youtubeKey=key;$('youtubePrivacy').value=y.privacy;$('youtubeLimit').value=y.daily_upload_limit}}
function renderReviewYouTube(m){const url=m.youtube?.url;$('reviewYoutube').hidden=!m.youtube;$('reviewYoutubeLink').hidden=!url;$('retryYoutube').hidden=!m.youtube||['cleaned','needs_review'].includes(m.youtube.state);text('reviewYoutubeState',(m.youtube?.state||'').replaceAll('_',' ')+(m.youtube?.error?' · '+m.youtube.error:''));if(url){$('reviewYoutubeLink').href=url;}$('preparePlayback').hidden=!!m.files?.['video.mp4']||!m.files?.['video.mkv']||m.state==='recording';if(!m.files?.['video.mp4']&&url&&!m.internet_archive?.verified_at&&$('player').getAttribute('src')){$('player').pause();$('player').removeAttribute('src');$('player').load();$('player').hidden=true}}

let reviewMediaKey='';
function renderDownloads(m){const key=JSON.stringify([m.id,m.files,m.youtube?.url]);if(key===reviewMediaKey)return;reviewMediaKey=key;const links=$('downloads');links.replaceChildren();for(const [name,label]of [['video.mkv','Original video archive'],['video.mp4','Playback MP4'],['rf.jsonl','RF JSONL'],['rf-trigger-events.json','RF trigger evidence'],['motion-events.json','Motion trigger evidence'],['buffer-state.json','Buffer timing'],['manifest.json','Session manifest'],['capture.log','Capture log'],['stimulus.wav','CE5 stimulus WAV'],['playback.log','Playback log'],['frames/index.json','Frame index']]){if(name!=='manifest.json'&&!m.files?.[name])continue;const a=el('a',label);a.href=`/sessions/${m.id}/${name}`;a.download=name;links.append(a)}for(const e of m.motion_events||[]){for(const file of e.evidence_files||[]){if(!/^motion-[a-f0-9]{16}-(before|after|boxed)\.jpg$/.test(file))continue;const a=el('a',file.endsWith('-before.jpg')?'Motion: before':'Motion: after');a.href=`/sessions/${m.id}/${file}`;a.target='_blank';a.rel='noopener';links.append(a)}}}
$('retryYoutube').onclick=()=>action('/api/youtube/retry',{id:selected.id});

function renderArchive(a){
 if(!a)return;
 text('archivePhase',a.phase.replaceAll('_',' ').toUpperCase());
 text('archiveConnection',a.configured?'Internet Archive keys configured.':'Internet Archive keys are required to start uploading.');
 text('archiveToggle',a.enabled?'Pause archive uploads':'Resume archive uploads');
 const count=Object.entries(a.counts||{}).map(([k,v])=>`${v} ${k.replaceAll('_',' ')}`).join(' · ');
 const progress=a.current?.total_bytes?` · ${a.current.id}: ${(a.current.uploaded_bytes/a.current.total_bytes*100).toFixed(0)}% transferred`:'';
 text('archiveStatus',(count||'Waiting for a completed MP4 and selected stills.')+progress);
 text('archiveError',a.error||'');
}
$('archiveSave').onclick=async()=>{
 if(await action('/api/archive/configure',{access_key:$('archiveAccessKey').value,secret_key:$('archiveSecretKey').value})){
  $('archiveAccessKey').value='';$('archiveSecretKey').value='';notice('Internet Archive keys saved. The upload queue will start automatically.');
 }
};
$('archiveToggle').onclick=()=>action('/api/archive/configure',{enabled:!state.internet_archive.enabled});
function renderReviewArchive(m){
 const archive=m.internet_archive;
 $('reviewArchive').hidden=!archive;
 if(!archive)return;
 $('reviewArchiveLink').href=archive.url;text('reviewArchiveState',(archive.state||'').replaceAll('_',' '));
 if(!m.files?.['video.mp4']&&archive.verified_at&&archive.video_url){
  const player=$('player');player.hidden=false;
  if(player.getAttribute('src')!==archive.video_url)player.src=archive.video_url;
 }
}

// Display-only overlay: camera packets and archival video never pass through it.
let motionOverlayDeadline=0;
function clearLiveMotionBoxes(){ $('liveMotionBoxes').replaceChildren(); }
async function pollLiveMotionBoxes(){
 try{
  if(document.hidden){clearLiveMotionBoxes();return}
  const response=await fetch('/api/motion-overlay',{cache:'no-store',signal:AbortSignal.timeout(1500)});
  if(!response.ok)throw Error('Motion overlay unavailable');
  const data=await response.json(),overlay=$('liveMotionBoxes');
  clearLiveMotionBoxes();
  const target=data.manual_target;
  $('stopTarget').hidden=!target||target.state==='lost';
  if(target){
   const box=document.createElementNS('http://www.w3.org/2000/svg','rect');
   const sx=(data.width||1920)/target.width,sy=(data.height||1080)/target.height;
   for(const [key,value] of Object.entries({x:target.left*sx,y:target.top*sy,width:(target.right-target.left)*sx,height:(target.bottom-target.top)*sy}))box.setAttribute(key,value);
   box.style.stroke=target.state==='tracking'?'#70f5d0':'#ff7984';overlay.append(box);
   const label=document.createElementNS('http://www.w3.org/2000/svg','text');label.setAttribute('x',target.left*sx);label.setAttribute('y',Math.max(18,target.top*sy-8));label.setAttribute('fill','#70f5d0');label.setAttribute('font-size','20');label.textContent=target.state==='tracking'?(target.label||'SELECTED TARGET'):'TARGET LOST';overlay.append(label);
   overlay.setAttribute('viewBox',`0 0 ${data.width||1920} ${data.height||1080}`);motionOverlayDeadline=performance.now()+700;
  }
  if(!data.frame_epoch||!data.width||!data.height)return;
  overlay.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);
  for(const box of data.boxes){
   const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
   rect.setAttribute('x',Math.max(0,box.left-8));rect.setAttribute('y',Math.max(0,box.top-8));
   rect.setAttribute('width',Math.min(data.width,box.right+8)-Math.max(0,box.left-8));
   rect.setAttribute('height',Math.min(data.height,box.bottom+8)-Math.max(0,box.top-8));overlay.append(rect);
   const label=document.createElementNS('http://www.w3.org/2000/svg','text');
   label.setAttribute('x',Math.max(0,Math.min(data.width-260,box.left-8)));label.setAttribute('y',Math.max(22,box.top-14));
   label.setAttribute('fill','#ffcf33');label.setAttribute('font-size','20');label.setAttribute('paint-order','stroke');label.setAttribute('stroke','#071013');label.setAttribute('stroke-width','4');label.setAttribute('stroke-linejoin','round');label.textContent=box.label||'Motion | analyzing';overlay.append(label);

  }
  motionOverlayDeadline=performance.now()+700;
 }catch(error){clearLiveMotionBoxes()}
 finally{setTimeout(pollLiveMotionBoxes,200)}
}
setInterval(()=>{if(performance.now()>motionOverlayDeadline||document.hidden)clearLiveMotionBoxes()},200);
pollLiveMotionBoxes();

$('preview').addEventListener('click',async event=>{
 if(regionEditing)return;
 const rect=$('preview').getBoundingClientRect();
 const result=await action('/api/motion/target',{x:(event.clientX-rect.left)/rect.width,y:(event.clientY-rect.top)/rect.height});
 if(result){$('stopTarget').hidden=false;notice('Target selected. Recording requested.');resetCameraChrome()}
});
$('stopTarget').onclick=async()=>{if(await action('/api/motion/target',{stop:true}))$('stopTarget').hidden=true};

// iPadOS may ignore CSS cursor shapes; draw the aiming reticle in the preview.
function positionAimCrosshair(event){
 const aim=$('aimCrosshair');
 if(regionEditing){aim.hidden=true;return}
 const rect=$('preview').getBoundingClientRect();
 const x=(event.clientX-rect.left)/rect.width,y=(event.clientY-rect.top)/rect.height;
 aim.hidden=x<0||x>1||y<0||y>1;
 aim.style.left=`${x*100}%`;aim.style.top=`${y*100}%`;
}
for(const event of ['pointermove','pointerdown'])$('preview').addEventListener(event,positionAimCrosshair);
$('preview').addEventListener('pointerleave',event=>{if(event.pointerType!=='touch')$('aimCrosshair').hidden=true});
$('preview').addEventListener('pointercancel',()=>{$('aimCrosshair').hidden=true});
