'use strict';
function displayLabel(value){return value==='house'?'Building/Structure':value.replaceAll('_',' ')}
const id=new URLSearchParams(location.search).get('id'),video=document.querySelector('#video'),canvas=document.querySelector('#frame'),ctx=canvas.getContext('2d'),statusEl=document.querySelector('#status'),scrub=document.querySelector('#scrub'),label=document.querySelector('#label');
let data,token,box=null,drag=null,ready=false,selectedId=null,annotations=[],dirty=false,busy=false,initialFrame=true,loadingData=false;
function status(text,error=false){statusEl.textContent=text;statusEl.classList.toggle('error',error)}
function frameAt(t){const times=data?.clip?.frame_times||[];let lo=0,hi=times.length-1;while(lo<=hi){const mid=(lo+hi)>>1;if(times[mid]<=t+.001)lo=mid+1;else hi=mid-1}return times[Math.max(0,hi)]??t}
function draw(){if(video.readyState>=2)ctx.drawImage(video,0,0,canvas.width,canvas.height);ctx.lineWidth=3*canvas.width/Math.max(1,canvas.getBoundingClientRect().width);const t=frameAt(video.currentTime);for(const a of annotations){if(a.sample_id!==selectedId&&Math.abs(a.review_clip_time-t)<.003){ctx.strokeStyle='#62e0e6';ctx.strokeRect(...a.bounds)}}if(box){ctx.strokeStyle='#ffdc00';ctx.strokeRect(...box)}document.querySelector('#time').textContent=t.toFixed(3)+' s';scrub.value=video.currentTime;document.querySelector('#selection').textContent=box?(selectedId?'Editing: ':'New object: ')+box.map(Math.round).join(', ')+' (native pixels)':'Drag a new box on this frame. Saved boxes are cyan.';const save=document.querySelector('#save');save.disabled=busy||!ready||!box||!video.paused||video.seeking;document.querySelector('#done').disabled=busy||!ready||video.seeking;save.textContent=selectedId?'Update annotation':'Add annotation'}
function animate(){draw();if(!video.paused)requestAnimationFrame(animate)}
async function request(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)});const result=await r.json();if(!r.ok)throw Error(result.error);return result}
function choose(a){dirty=false;video.pause();selectedId=a.sample_id;box=[...a.bounds];label.value=a.label;video.currentTime=a.review_clip_time;draw()}
function listing(){document.querySelector('#count').textContent=annotations.length;const list=document.querySelector('#annotations');list.replaceChildren();if(!annotations.length){list.textContent='No saved annotations yet.';return}for(const a of [...annotations].sort((a,b)=>a.review_clip_time-b.review_clip_time)){const row=document.createElement('div');row.className='annotation';row.dataset.sampleId=a.sample_id;const text=document.createElement('span');text.textContent=a.review_clip_time.toFixed(3)+' s · '+displayLabel(a.label);const edit=document.createElement('button');edit.textContent='Jump / edit';edit.onclick=()=>choose(a);const remove=document.createElement('button');remove.textContent='Remove';remove.onclick=async()=>{try{await request('/api/email-review/delete',{id,sample_id:a.sample_id});annotations=annotations.filter(v=>v.sample_id!==a.sample_id);if(selectedId===a.sample_id){selectedId=null;box=null}showCompletion(false);listing();draw();status('Annotation removed; review history retained.')}catch(e){status(e.message,true)}};row.append(text,edit,remove);list.append(row)}}
async function load(){if(loadingData)return;loadingData=true;try{const r=await fetch('/api/email-review?id='+encodeURIComponent(id));data=await r.json();if(!r.ok)throw Error(data.error);token=data.token;if(data.clip.state!=='ready'){status(data.clip.error||'Preparing the surrounding native video…',!!data.clip.error);setTimeout(load,4000);return}annotations=data.annotations;listing();showCompletion(data.completed);label.replaceChildren(...data.labels.map(v=>new Option(displayLabel(v),v)));label.value=data.label;if(!video.getAttribute('src'))video.src='/api/email-review/video?id='+encodeURIComponent(id);status(data.completed?'Review complete. All annotations saved.':'Loading video… If it stays blank, tap Load video.');frameReady()}catch(e){status(e.message,true)}finally{loadingData=false}}
video.addEventListener('loadedmetadata',()=>{canvas.width=video.videoWidth;canvas.height=video.videoHeight;scrub.max=Math.max(0,video.duration-.001);if(data?.clip?.state==='ready'){video.currentTime=data.clip.event_time;box=data.event.bounds}});
function frameReady(){
 if(video.readyState<2||video.seeking||data?.clip?.state!=='ready')return;
 if(initialFrame&&data?.clip?.state==='ready'){
  video.pause();
  if(Math.abs(video.currentTime-data.clip.event_time)>.025){video.currentTime=data.clip.event_time;return}
  initialFrame=false;box=data.event.bounds;
 }
 ready=true;document.querySelector('#load-help').hidden=true;
 for(const key of ['play','prev','next','scrub','reset','new'])document.getElementById(key).disabled=false;
 status(data?.completed?'Review complete. All annotations saved.':'Scrub, pause, and draw a box. Add more objects on this frame or another frame.');draw();
}
video.addEventListener('loadeddata',frameReady);video.addEventListener('seeked',()=>{if(!ready)frameReady();else draw()});
document.querySelector('#load-video').onclick=()=>{
 // Keep load/play synchronous with the tap: iOS may decline hidden-media preload.
 status('Loading video…');video.muted=true;
 if(!video.getAttribute('src'))video.src='/api/email-review/video?id='+encodeURIComponent(id);
 video.load();const playing=video.play();
 if(playing)playing.then(()=>{if(initialFrame)frameReady()}).catch(()=>{if(!ready)status('Tap Load video again to start playback.',true)});
 if(!data)load();
};
video.addEventListener('error',()=>{document.querySelector('#load-help').hidden=false;status('The video could not be loaded. Tap Load video to retry.',true)});video.addEventListener('pause',()=>{document.querySelector('#play').textContent='Play';draw()});video.addEventListener('play',()=>{box=null;selectedId=null;document.querySelector('#play').textContent='Pause';animate()});
document.querySelector('#play').onclick=()=>{if(video.paused)video.play().catch(()=>status('Playback could not start. Tap Play to retry.',true));else video.pause()};
function seek(t){dirty=false;video.pause();box=null;selectedId=null;video.currentTime=Math.max(0,Math.min(video.duration-.001,t));draw()}
scrub.oninput=()=>seek(Number(scrub.value));document.querySelector('#prev').onclick=()=>{const times=data.clip.frame_times,index=times.indexOf(frameAt(video.currentTime));seek(times[Math.max(0,index-1)])};document.querySelector('#next').onclick=()=>{const times=data.clip.frame_times,index=times.indexOf(frameAt(video.currentTime));seek(times[Math.min(times.length-1,index+1)])};
document.querySelector('#reset').onclick=()=>{dirty=false;video.pause();selectedId=null;video.currentTime=data.clip.event_time;box=data.event.bounds;draw()};document.querySelector('#new').onclick=()=>{dirty=false;video.pause();selectedId=null;box=null;draw()};
function point(e){const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(canvas.width,(e.clientX-r.left)*canvas.width/r.width)),Math.max(0,Math.min(canvas.height,(e.clientY-r.top)*canvas.height/r.height))]}
canvas.onpointerdown=e=>{if(!ready||busy||video.seeking)return;dirty=true;video.pause();drag=point(e);canvas.setPointerCapture(e.pointerId);box=null};canvas.onpointermove=e=>{if(!drag)return;const p=point(e);box=[Math.min(drag[0],p[0]),Math.min(drag[1],p[1]),Math.abs(p[0]-drag[0]),Math.abs(p[1]-drag[1])];draw()};canvas.onpointerup=()=>{if(!drag)return;drag=null;if(!box||box[2]<3||box[3]<3)box=null;draw()};canvas.onpointercancel=()=>{drag=null;box=null;draw()};
async function saveSelection(){const result=await request('/api/email-review/save',{id,label:label.value,time:frameAt(video.currentTime),bounds:box,sample_id:selectedId});const a=result.review;annotations=annotations.filter(v=>v.sample_id!==a.sample_id);annotations.push(a);selectedId=null;box=null;dirty=false;showCompletion(false);listing();status('Saved '+displayLabel(a.label)+'. '+annotations.length+' annotation(s). Draw another object or scrub to another frame.')}
function showCompletion(completed){if(data)data.completed=completed;document.querySelector('#complete').hidden=!completed;document.querySelector('#editor').hidden=false;}
label.onchange=()=>{if(box)dirty=true};
document.querySelector('#save').onclick=async()=>{if(busy)return;busy=true;draw();try{await saveSelection()}catch(e){status(e.message,true)}finally{busy=false;draw()}};
document.querySelector('#done').onclick=async()=>{if(busy)return;video.pause();busy=true;draw();try{if(dirty&&box)await saveSelection();await request('/api/email-review/finish',{id,completed:true});showCompletion(true);status('Review complete. All annotations saved.')}catch(e){status(e.message,true)}finally{busy=false;draw()}};
document.querySelector('#reopen').onclick=async()=>{if(busy)return;const button=document.querySelector('#reopen');busy=true;button.disabled=true;button.textContent='Reopening…';status('Reopening review. You can still watch and scrub the video.');try{await request('/api/email-review/finish',{id,completed:false});showCompletion(false);box=null;dirty=false;status('Review reopened. Add or edit your annotations.');frameReady();draw()}catch(e){status('Could not reopen review: '+e.message,true)}finally{busy=false;button.disabled=false;button.textContent='Reopen review';draw()}};
window.addEventListener('resize',draw);load();
window.addEventListener('station-reconnected',e=>{token=e.detail.token;});
