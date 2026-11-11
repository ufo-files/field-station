'use strict';
function displayLabel(value){return value==='cloud'?'Cloud/Sky':value==='house'?'Building/Structure':value.replaceAll('_',' ')}
const id=new URLSearchParams(location.search).get('id'),video=document.querySelector('#video'),canvas=document.querySelector('#frame'),ctx=canvas.getContext('2d'),statusEl=document.querySelector('#status'),scrub=document.querySelector('#scrub'),label=document.querySelector('#label');
let data,token,box=null,drag=null,ready=false,selectedId=null,annotations=[],dirty=false,busy=false,initialFrame=true,loadingData=false;
let hoverPoint=null,hoverFrame=null;
const sizeControl=document.querySelector('#annotation-size'),zoomCanvas=document.querySelector('#annotation-zoom'),zoomContext=zoomCanvas.getContext('2d');
try{const saved=localStorage.getItem('field-station.annotation-size');if(['64','128','256','512'].includes(saved))sizeControl.value=saved;}catch{}
function fixedBox(p){const side=Math.min(Number(sizeControl.value),canvas.width,canvas.height);return [Math.round(Math.max(0,Math.min(canvas.width-side,p[0]-side/2))),Math.round(Math.max(0,Math.min(canvas.height-side,p[1]-side/2))),side,side];}
sizeControl.onchange=()=>{try{localStorage.setItem('field-station.annotation-size',sizeControl.value)}catch{}if(box){box=fixedBox([box[0]+box[2]/2,box[1]+box[3]/2]);dirty=true;}draw();};
function drawHover(){
 if(!hoverPoint||!ready||!video.paused||video.seeking||busy){zoomCanvas.hidden=true;return;}
 const [x,y]=hoverPoint,r=canvas.getBoundingClientRect(),scale=canvas.width/Math.max(1,r.width),preview=fixedBox(hoverPoint);
 ctx.save();ctx.strokeStyle='#fff';ctx.lineWidth=scale;ctx.setLineDash([4*scale,4*scale]);ctx.strokeRect(...preview);ctx.setLineDash([]);ctx.beginPath();ctx.moveTo(x-12*scale,y);ctx.lineTo(x+12*scale,y);ctx.moveTo(x,y-12*scale);ctx.lineTo(x,y+12*scale);ctx.stroke();ctx.restore();
 zoomCanvas.hidden=false;const z=zoomCanvas.getBoundingClientRect().width,px=x/canvas.width*r.width,py=y/canvas.height*r.height;zoomCanvas.style.left=Math.max(0,Math.min(r.width-z,px+z+24<r.width?px+24:px-z-24))+'px';zoomCanvas.style.top=Math.max(0,Math.min(r.height-z,py-z/2))+'px';
 const [sx,sy,span]=preview,w=zoomCanvas.width;
 zoomContext.clearRect(0,0,w,w);zoomContext.imageSmoothingEnabled=false;zoomContext.drawImage(video,sx,sy,span,span,0,0,w,w);const zx=(x-sx)/span*w,zy=(y-sy)/span*w;zoomContext.strokeStyle='#fff';zoomContext.lineWidth=2;zoomContext.beginPath();zoomContext.moveTo(zx-14,zy);zoomContext.lineTo(zx+14,zy);zoomContext.moveTo(zx,zy-14);zoomContext.lineTo(zx,zy+14);zoomContext.stroke();zoomContext.strokeStyle='#ffdc00';zoomContext.strokeRect((preview[0]-sx)/span*w,(preview[1]-sy)/span*w,preview[2]/span*w,preview[3]/span*w);
}
function status(text,error=false){const stageStatus=document.querySelector('#stage-status'),target=ready?statusEl:stageStatus;statusEl.hidden=true;stageStatus.hidden=true;target.textContent=text;target.hidden=!text;target.classList.toggle('error',error)}
function frameAt(t){const times=data?.clip?.frame_times||[];let lo=0,hi=times.length-1;while(lo<=hi){const mid=(lo+hi)>>1;if(times[mid]<=t+.001)lo=mid+1;else hi=mid-1}return times[Math.max(0,hi)]??t}
function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);ctx.lineWidth=3*canvas.width/Math.max(1,canvas.getBoundingClientRect().width);const t=frameAt(video.currentTime);for(const a of annotations){if(a.sample_id!==selectedId&&Math.abs(a.review_clip_time-t)<.003){ctx.strokeStyle='#62e0e6';ctx.strokeRect(...a.bounds)}}if(box){ctx.strokeStyle='#ffdc00';ctx.strokeRect(...box)}document.querySelector('#time').textContent=t.toFixed(3)+' s';scrub.value=pendingSeek??video.currentTime;document.querySelector('#selection').textContent=box?(selectedId?'Editing: ':'New object: ')+box.map(Math.round).join(', ')+' (native pixels)':'Click to place a fixed-size box. Drag to reposition. Saved boxes are cyan.';const save=document.querySelector('#save');save.disabled=busy||!ready||!box||!video.paused||video.seeking;save.textContent=selectedId?'Update annotation':'Add annotation';drawHover()}
let renderHandle=null,lastRenderedTime=-1,pendingSeek=null;
function stopAnimation(){if(renderHandle!==null){if(video.cancelVideoFrameCallback)video.cancelVideoFrameCallback(renderHandle);else cancelAnimationFrame(renderHandle);renderHandle=null;}}
function animate(){renderHandle=null;if(video.paused)return;if(stopAtTrimEnd())return;const t=frameAt(video.currentTime);if(t!==lastRenderedTime){lastRenderedTime=t;draw();}renderHandle=video.requestVideoFrameCallback?video.requestVideoFrameCallback(animate):requestAnimationFrame(animate);}

async function request(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)});const result=await r.json();if(!r.ok)throw Error(result.error);return result}
function choose(a){if(savedRange()&&(a.review_clip_time<savedRange()[0]||a.review_clip_time>=savedRange()[1])){showFullVideo=true;updatePlayerRange();}dirty=false;video.pause();selectedId=a.sample_id;box=[...a.bounds];label.value=a.label;video.currentTime=a.review_clip_time;draw()}
function listing(){document.querySelector('#count').textContent=annotations.length;const list=document.querySelector('#annotations');list.replaceChildren();if(!annotations.length){list.textContent='No saved annotations yet.';return}for(const a of [...annotations].sort((a,b)=>a.review_clip_time-b.review_clip_time)){const row=document.createElement('div');row.className='annotation';row.dataset.sampleId=a.sample_id;const text=document.createElement('span');text.textContent=a.review_clip_time.toFixed(3)+' s · '+displayLabel(a.label);const edit=document.createElement('button');edit.textContent='Jump / edit';edit.onclick=()=>choose(a);const remove=document.createElement('button');remove.textContent='Remove';remove.onclick=async()=>{try{await request('/api/email-review/delete',{id,sample_id:a.sample_id});annotations=annotations.filter(v=>v.sample_id!==a.sample_id);if(selectedId===a.sample_id){selectedId=null;box=null}showCompletion(true);loadTrim();listing();draw();status('Annotation removed; review history retained.')}catch(e){status(e.message,true)}};row.append(text,edit,remove);list.append(row)}}
async function load(){if(loadingData)return;loadingData=true;try{const r=await fetch('/api/email-review?id='+encodeURIComponent(id));data=await r.json();if(!r.ok)throw Error(data.error);token=data.token;if(data.clip.state!=='ready'){status(data.clip.error||(data.clip.phase==='playback'?'Preparing playback…':'Preparing the surrounding video…'),!!data.clip.error);if(!data.clip.error)setTimeout(load,1000);return}annotations=data.annotations;listing();showCompletion(data.completed);label.replaceChildren(...data.labels.map(v=>new Option(displayLabel(v),v)));label.value=data.label;if(!video.getAttribute('src'))video.src='/api/email-review/video?id='+encodeURIComponent(id);document.querySelector('#play').disabled=false;status('Preparing the surrounding video…');frameReady()}catch(e){status(e.message,true)}finally{loadingData=false}}
video.addEventListener('loadedmetadata',()=>{canvas.width=video.videoWidth;canvas.height=video.videoHeight;scrub.max=Math.max(0,video.duration-.001);if(data?.clip?.state==='ready'){video.currentTime=data.clip.event_time;box=data.event.bounds}});
function frameReady(){
 if(video.readyState<2||video.seeking||data?.clip?.state!=='ready')return;
 if(initialFrame&&data?.clip?.state==='ready'){
  video.pause();
  const target=Math.max(playerRange()[0],Math.min(playerRange()[1]-.002,data.clip.event_time));if(Math.abs(video.currentTime-target)>.025){video.currentTime=target;return}
  initialFrame=false;box=data.event.bounds;
 }
 ready=true;document.querySelector('.review-stage').classList.remove('is-loading');
 for(const key of ['play','prev','next','scrub','reset','new'])document.getElementById(key).disabled=false;
 status('');draw();updatePlayerRange();updateTrimButtons();
}
video.addEventListener('loadeddata',frameReady);video.addEventListener('seeked',()=>{if(pendingSeek!==null){const target=pendingSeek;pendingSeek=null;if(Math.abs(video.currentTime-target)>.001){video.currentTime=target;return;}}if(!ready)frameReady();else draw()});
function startVideo(){
 // Keep load/play synchronous with the tap: iOS may decline hidden-media preload.
 if(data?.clip?.state!=='ready'){load();return;}
 status('Loading video…');video.muted=true;
 if(!video.getAttribute('src'))video.src='/api/email-review/video?id='+encodeURIComponent(id);
 video.load();const playing=video.play();
 if(playing)playing.then(()=>{if(initialFrame)frameReady()}).catch(()=>{if(!ready)status('Playback could not start. Tap Play to retry.',true)});
 if(!data)load();
};
video.addEventListener('error',()=>{status('The video could not be loaded. Refresh to retry.',true)});video.addEventListener('pause',()=>{stopAnimation();document.querySelector('#play').textContent='Play';draw()});video.addEventListener('play',()=>{box=null;selectedId=null;document.querySelector('#play').textContent='Pause';stopAnimation();lastRenderedTime=-1;animate()});
document.querySelector('#play').onclick=()=>{if(!ready){startVideo();return}trimPlaying=false;if(video.paused){const [start,end]=playerRange();if(video.currentTime<start||video.currentTime>=end-.03)video.currentTime=start;video.play().catch(()=>status('Playback could not start. Tap Play to retry.',true));}else video.pause()};
function seek(t){if(!ready)return;trimPlaying=false;dirty=false;video.pause();box=null;selectedId=null;const target=Math.max(playerRange()[0],Math.min(frameAt(playerRange()[1]-.002),t));if(video.seeking)pendingSeek=target;else video.currentTime=target;draw()}
scrub.oninput=()=>seek(Number(scrub.value));document.querySelector('#prev').onclick=()=>{const times=data.clip.frame_times,index=times.indexOf(frameAt(video.currentTime));seek(times[Math.max(0,index-1)])};document.querySelector('#next').onclick=()=>{const times=data.clip.frame_times,index=times.indexOf(frameAt(video.currentTime));seek(times[Math.min(times.length-1,index+1)])};
document.querySelector('#reset').onclick=()=>{dirty=false;video.pause();selectedId=null;video.currentTime=Math.max(playerRange()[0],Math.min(playerRange()[1]-.002,data.clip.event_time));box=data.event.bounds;draw()};document.querySelector('#new').onclick=()=>{dirty=false;video.pause();selectedId=null;box=null;draw()};
function point(e){const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(canvas.width,(e.clientX-r.left)*canvas.width/r.width)),Math.max(0,Math.min(canvas.height,(e.clientY-r.top)*canvas.height/r.height))]}
canvas.onpointerdown=e=>{if(!ready||busy||video.seeking||e.button!==0)return;dirty=true;video.pause();drag=point(e);hoverPoint=drag;canvas.setPointerCapture(e.pointerId);box=fixedBox(drag);draw()};
canvas.onpointermove=e=>{hoverPoint=point(e);if(drag)box=fixedBox(hoverPoint);if(hoverFrame===null)hoverFrame=requestAnimationFrame(()=>{hoverFrame=null;draw()})};
canvas.onpointerup=e=>{if(!drag)return;box=fixedBox(point(e));drag=null;if(e.pointerType==='touch')hoverPoint=null;draw()};
canvas.onpointerleave=()=>{if(!drag){hoverPoint=null;draw()}};
canvas.onpointercancel=()=>{drag=null;hoverPoint=null;box=null;draw()};

async function saveSelection(){const result=await request('/api/email-review/save',{id,label:label.value,time:frameAt(video.currentTime),bounds:box,sample_id:selectedId});const a=result.review;annotations=annotations.filter(v=>v.sample_id!==a.sample_id);annotations.push(a);selectedId=null;box=null;dirty=false;showCompletion(true);loadTrim();listing();status('Saved '+displayLabel(a.label)+'. '+annotations.length+' annotation(s). Place another box or scrub to another frame.')}
function showCompletion(completed){if(data)data.completed=completed;document.querySelector('#editor').hidden=false;}
label.onchange=()=>{if(box)dirty=true};
document.querySelector('#save').onclick=async()=>{if(busy)return;busy=true;draw();try{await saveSelection()}catch(e){status(e.message,true)}finally{busy=false;draw()}};
window.addEventListener('resize',draw);load();
window.addEventListener('station-reconnected',e=>{token=e.detail.token;});

let trimPlaying=false,trimState=null,trimTimer=null,showFullVideo=false;
const trimStart=document.querySelector('#trim-start'),trimEnd=document.querySelector('#trim-end'),trimMessage=document.querySelector('#trim-status');
function trimDuration(){const t=data?.clip?.frame_times||[];return Number.isFinite(video.duration)?video.duration:t.length>1?t.at(-1)+(t.at(-1)-t.at(-2)):0;}
function savedRange(){const r=trimState?.request;return r?.enabled&&r.event_id===id?[r.start,r.end]:null;}
function playerRange(){return !showFullVideo&&savedRange()||[0,trimDuration()];}
function updatePlayerRange(){const range=playerRange();scrub.min=range[0];scrub.max=Math.max(range[0],range[1]-.002);const button=document.querySelector('#trim-view-full');button.hidden=!savedRange();button.textContent=showFullVideo?'Show saved trim':'Show full video';if(ready&&(video.currentTime<range[0]||video.currentTime>=range[1])){video.pause();video.currentTime=range[0];}draw();}
function stopAtTrimEnd(){const end=trimPlaying?Number(trimEnd.value):!showFullVideo&&savedRange()?savedRange()[1]:null;if(end!==null&&video.currentTime>=end-.001){trimPlaying=false;video.pause();return true;}return false;}
document.querySelector('#trim-view-full').onclick=()=>{video.pause();trimPlaying=false;showFullVideo=!showFullVideo;updatePlayerRange();};
function trimValid(){return Number.isFinite(Number(trimStart.value))&&Number.isFinite(Number(trimEnd.value))&&Number(trimStart.value)>=0&&Number(trimEnd.value)>Number(trimStart.value)&&Number(trimEnd.value)<=trimDuration()+.01;}
function updateTrimButtons(){const available=ready&&trimState?.available&&!busy;for(const name of ['trim-start','trim-end','trim-set-start','trim-set-end','trim-reset'])document.getElementById(name).disabled=!available;for(const name of ['trim-preview','trim-save'])document.getElementById(name).disabled=!available||!trimValid();stopAtTrimEnd();}
async function loadTrim(initial=false){clearTimeout(trimTimer);try{const r=await fetch('/api/email-review/trim?id='+encodeURIComponent(id));if(!r.ok)throw Error('Could not load trim settings.');const previousRevision=trimState?.request?.revision;trimState=await r.json();if(initial||previousRevision!==trimState.request?.revision)showFullVideo=false;updatePlayerRange();const bundle=document.querySelector('#bundle-download');bundle.disabled=!trimState.bundle_url;bundle.textContent=trimState.bundle_updating?'Bundle updating…':'Download bundle';bundle.title=trimState.bundle_url?'Download all archived videos, reviewed frames, annotations, and metadata as ZIP':'Available after the current Archive upload is verified';const saved=trimState.request||{};if(initial||!trimStart.value){trimStart.value=(saved.enabled&&saved.event_id===id?saved.start:0).toFixed(3);trimEnd.value=(saved.enabled&&saved.event_id===id?saved.end:trimDuration()).toFixed(3);}trimMessage.textContent=!trimState.available?'Trimming becomes available when this detection is linked to its recording.':trimState.error?'Trim needs attention: '+trimState.error:saved.revision&&!trimState.applied?'Preparing the saved range for download and Internet Archive…':saved.enabled?'Trim saved. Full original and training annotations preserved.':'Full recording selected. Trimming also updates its Internet Archive video.';document.querySelector('#trim-download').hidden=!trimState.applied;document.querySelector('#trim-download').href='/api/email-review/trim/video?id='+encodeURIComponent(id);if((saved.revision&&!trimState.applied)||!trimState.bundle_url)trimTimer=setTimeout(()=>loadTrim(),5000);updateTrimButtons();}catch(e){trimMessage.textContent=e.message;}}
for(const input of [trimStart,trimEnd])input.oninput=()=>{trimPlaying=false;updateTrimButtons();};
document.querySelector('#trim-set-start').onclick=()=>{trimStart.value=frameAt(video.currentTime).toFixed(3);updateTrimButtons();};
document.querySelector('#trim-set-end').onclick=()=>{const times=data.clip.frame_times,t=frameAt(video.currentTime),next=times.find(v=>v>t+.001);trimEnd.value=(next??trimDuration()).toFixed(3);updateTrimButtons();};
document.querySelector('#trim-preview').onclick=()=>{video.pause();box=null;selectedId=null;video.currentTime=Number(trimStart.value);trimPlaying=true;video.play().catch(e=>{trimPlaying=false;trimMessage.textContent=e.message;});};
video.addEventListener('timeupdate',updateTrimButtons);video.addEventListener('loadedmetadata',()=>loadTrim(true));
async function saveTrim(reset=false){if(busy)return;video.pause();trimPlaying=false;busy=true;updateTrimButtons();trimMessage.textContent='Saving trim…';try{await request('/api/email-review/trim',reset?{id,reset:true}:{id,start:Number(trimStart.value),end:Number(trimEnd.value)});await loadTrim(reset);}catch(e){trimMessage.textContent=e.message;}finally{busy=false;updateTrimButtons();}}
document.querySelector('#trim-save').onclick=()=>saveTrim();document.querySelector('#trim-reset').onclick=()=>saveTrim(true);

document.querySelector('#bundle-download').onclick=()=>{if(trimState?.bundle_url)window.location.assign(trimState.bundle_url);};

// Session tags save independently of annotations and video exports.
(()=>{
 const input=document.getElementById('video-tags'),message=document.getElementById('tags-status'),automatic=document.getElementById('automatic-tags');
 let revision=null,saving=false,changed=false,timer;
 async function loadTags(){try{const response=await fetch('/api/email-review/tags?id='+encodeURIComponent(id));const state=await response.json();if(!response.ok)throw Error(state.error);if(!state.available){message.textContent='Tags become available when this detection is linked to a recording.';setTimeout(loadTags,5000);return;}revision=state.revision;input.value=state.custom.join(', ');automatic.replaceChildren(...state.automatic.map(tag=>{const pill=document.createElement('span');pill.textContent=tag;pill.title='Automatic tag';return pill;}));input.disabled=false;message.textContent='';}catch(e){message.textContent=e.message;}}
 async function saveTags(){clearTimeout(timer);if(saving||!changed)return;if(!token){timer=setTimeout(saveTags,500);return;}saving=true;changed=false;message.textContent='Saving tags…';const value=input.value;try{const result=await request('/api/email-review/tags',{id,tags:value.split(','),revision});revision=result.revision;message.textContent=changed?'Saving tags…':'Tags saved';}catch(e){changed=true;message.textContent='Tags not saved: '+e.message;}finally{saving=false;if(changed&&value!==input.value)timer=setTimeout(saveTags,500);}}
 input.addEventListener('input',()=>{changed=true;message.textContent='Saving tags…';clearTimeout(timer);timer=setTimeout(saveTags,700);});input.addEventListener('blur',saveTags);input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();saveTags();}});
 window.addEventListener('beforeunload',e=>{if(changed||saving){e.preventDefault();e.returnValue='';}});void loadTags();
})();
