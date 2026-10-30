const $=id=>document.getElementById(id);
const pretty=value=>value.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
let csrf='',items=[],offset=0,total=0,limit=60,detail=null,draft=[],selected=-1,image=null,drawMode=null,start=null,drawing=null,loading=false,dirty=false;
const canvas=$('reviewCanvas'),ctx=canvas.getContext('2d');
let visited=new Set(),skipped=0,saved=0,navigation=0;
function notice(message){$('reviewNotice').textContent=message;$('reviewNotice').hidden=!message}
async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json','X-Station-Token':csrf},body:JSON.stringify(body)}:{cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.error||'Request failed');if(data.csrf)csrf=data.csrf;return data}
function options(id,values){$(id).replaceChildren(...values.map(value=>new Option(pretty(value),value)))}
function updateCounts(data){
 $('summary').textContent=`${data.counts.reviewed} of ${data.counts.total} reviewed · ${data.counts.training_ready} training ready${skipped?' · '+skipped+' skipped this pass':''}`;
 if($('filterObject').options.length===1)for(const value of data.objects)$('filterObject').append(new Option(pretty(value),value));
}
async function nextFrame(){
 const generation=++navigation;resetSourceVideo();loading=true;targetControls();notice('');
 $('editorStatus').textContent='Loading next frame…';
 try{
  let page=0;
  while(true){
   const query=new URLSearchParams({offset:page,limit,search:$('search').value,object:$('filterObject').value,review:$('filterReview').value});
   const data=await api('/api/boxed-review/list?'+query);
   if(generation!==navigation)return;
   updateCounts(data);items=data.items;total=data.total;
   const candidate=items.find(item=>!visited.has(item.key));
   if(candidate){await openFrame(candidate.key,generation);return}
   page+=limit;if(page>=total)break;
  }
  loading=false;detail=null;image=null;draft=[];selected=-1;
  $('editor').hidden=true;$('emptyState').hidden=false;
  $('emptyTitle').textContent=total?'This pass is complete':'No frames need review';
  $('emptyMessage').textContent=total?'You have reviewed or skipped every matching frame in this pass. Skipped frames remain unreviewed.':'New matching captures will appear here. You can also change the filters.';
  $('restartPass').textContent=skipped?'Review skipped frames':'Check for new frames';
 }catch(e){if(generation===navigation){loading=false;notice(e.message);$('editorStatus').textContent='Could not load the next frame. Try Skip again.';targetControls()}}
}
async function resetPass(){
 if(dirty&&!confirm('Discard unsaved corrections?'))return;
 dirty=false;visited.clear();skipped=0;saved=0;await nextFrame();
}
function saveAllowed(){return !!detail&&!loading}
function targetControls(){
 $('targetSelect').replaceChildren(...draft.map((r,i)=>new Option(`Target ${i+1} · ${pretty(r.object)}`,String(i))));
 if(!draft.length)$('targetSelect').append(new Option('No targets','-1'));
 $('targetSelect').value=String(selected);
 for(const id of ['objectLabel','shapeLabel','redrawBox','removeBox'])$(id).disabled=loading||selected<0||(id==='shapeLabel'&&draft[selected]?.object==='cloud');
 if(selected>=0){$('objectLabel').value=draft[selected].object;$('shapeLabel').value=draft[selected].shape}
 for(const id of ['saveNext'])$(id).disabled=!saveAllowed();
 $('skipFrame').disabled=loading;
 $('targetSelect').disabled=loading;for(const id of ['addBox','noObject','reviewNote'])$(id).disabled=loading;
 $('boxesConfirmed').disabled=loading||!detail?.clean_image;
}
function displayBounds(region){
 const b=region.bounds,padding=detail?.human_review?16:Math.max(24,Math.round(Math.max(b.right-b.left,b.bottom-b.top)*.3));
 return {left:Math.max(0,b.left-padding),top:Math.max(0,b.top-padding),right:Math.min(canvas.width-1,b.right+padding),bottom:Math.min(canvas.height-1,b.bottom+padding)};
}
function draw(){
 if(!image)return;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0);
 for(const [i,r]of draft.entries()){
 if(r.object==='cloud')continue;
 const b=displayBounds(r);ctx.strokeStyle=i===selected?'#70f5d0':'#ffcf33';ctx.lineWidth=3;ctx.strokeRect(b.left,b.top,b.right-b.left,b.bottom-b.top);if(i===selected){const tight=r.bounds;ctx.save();ctx.lineWidth=1.5;ctx.setLineDash([5,4]);ctx.strokeRect(tight.left,tight.top,tight.right-tight.left,tight.bottom-tight.top);ctx.restore();}
 ctx.font='20px system-ui';const label=`T${i+1}: ${pretty(r.object)} | ${pretty(r.shape)}`,width=ctx.measureText(label).width,x=Math.max(0,Math.min(b.left,canvas.width-width-8)),y=Math.max(24,b.top-7);ctx.fillStyle='#071013';ctx.fillRect(x,y-22,width+8,27);ctx.fillStyle=i===selected?'#70f5d0':'#ffcf33';ctx.fillText(label,x+4,y);
 }
 const zoom=$('targetZoom'),z=zoom.getContext('2d');z.clearRect(0,0,zoom.width,zoom.height);
 if(selected>=0){const b=draft[selected].bounds,outer=displayBounds(draft[selected]),cx=(b.left+b.right)/2,cy=(b.top+b.bottom)/2,span=Math.max(48,outer.right-outer.left+16,outer.bottom-outer.top+16),l=Math.max(0,cx-span/2),t=Math.max(0,cy-span/2),w=Math.min(span,canvas.width-l),h=Math.min(span,canvas.height-t);z.imageSmoothingEnabled=true;z.imageSmoothingQuality='high';z.drawImage(image,l,t,w,h,0,0,zoom.width,zoom.height);z.strokeStyle='#70f5d0';z.lineWidth=2;if(draft[selected].object!=='cloud'){z.strokeRect((outer.left-l)/w*zoom.width,(outer.top-t)/h*zoom.height,(outer.right-outer.left)/w*zoom.width,(outer.bottom-outer.top)/h*zoom.height);z.setLineDash([5,4]);z.strokeRect((b.left-l)/w*zoom.width,(b.top-t)/h*zoom.height,(b.right-b.left)/w*zoom.width,(b.bottom-b.top)/h*zoom.height);z.setLineDash([])}}
 const closeup=$('targetDetail'),nativeLink=$('nativeCrop');
 const crop=selected>=0?detail?.detail_crops?.[selected]:null;
 const unchanged=selected>=0&&JSON.stringify(draft[selected].bounds)===JSON.stringify(detail?.regions?.[selected]?.bounds);
 if(crop&&unchanged){
  const url=crop.image_url+'&v='+encodeURIComponent(detail.human_review?.reviewed_at||'1');
  if(closeup.getAttribute('src')!==url)closeup.src=url;
  closeup.hidden=false;zoom.hidden=true;nativeLink.hidden=false;nativeLink.href=crop.native_url;
  $('detailCaption').textContent=`Smoothed enlargement · native crop ${crop.native_width} × ${crop.native_height} pixels`;
 }else{closeup.hidden=true;zoom.hidden=false;nativeLink.hidden=true;$('detailCaption').textContent='Smoothed live crop · save to retain this close-up';}
 if(drawing){ctx.strokeStyle='#70f5d0';ctx.setLineDash([8,6]);ctx.strokeRect(drawing.left,drawing.top,drawing.right-drawing.left,drawing.bottom-drawing.top);ctx.setLineDash([])}
}
async function openFrame(key,generation=navigation){
 loading=true;targetControls();
 const loadedDetail=await api('/api/boxed-review/detail?key='+encodeURIComponent(key));
 const loaded=new Image();loaded.src=loadedDetail.image_url+'&v='+Date.now();await loaded.decode();
 if(generation!==navigation)return;
 detail=loadedDetail;dirty=false;draft=structuredClone(detail.regions);selected=draft.length?0:-1;drawMode=null;drawing=null;start=null;
 options('objectLabel',detail.objects.filter(x=>x!=='no_object'));options('shapeLabel',detail.shapes);
 $('editorTitle').textContent=key;$('frameProgress').textContent=detail.human_review?'REVIEWED':'NEEDS REVIEW';
 $('reviewNote').value=detail.human_review?.note||'';$('boxesConfirmed').checked=detail.human_review?.boxes_confirmed||false;$('boxesConfirmed').disabled=!detail.clean_image;
 $('editorStatus').textContent=detail.clean_image?'Review the target, then Save & next.':'Original unavailable: label corrections are saved, but this frame is excluded from training.';
 $('modelInfo').textContent='Model: '+(detail.model_classification?.regions?.map(r=>pretty(r.object.label)).join(', ')||'Not analyzed')+'. Your labels take priority.';
 canvas.width=detail.width;canvas.height=detail.height;image=loaded;
 $('emptyState').hidden=true;$('editor').hidden=false;loading=false;targetControls();draw();resetSourceVideo();
}
$('targetSelect').onchange=()=>{selected=Number($('targetSelect').value);targetControls();draw()};
for(const [id,key]of [['objectLabel','object'],['shapeLabel','shape']])$(id).onchange=()=>{if(selected>=0){draft[selected][key]=$(id).value;if(key==='object'&&$(id).value==='cloud'){draft[selected].shape='unresolved';$('editorStatus').textContent='Cloud marked as background. Its box is hidden and it will be a negative training example.';}if(key==='object'&&$(id).value==='anomalous')$('editorStatus').textContent='Flagged as anomalous for follow-up. Its box and your shape label are retained.';dirty=true;$('boxesConfirmed').checked=false;targetControls();draw()}};
$('reviewNote').oninput=()=>{dirty=true};$('boxesConfirmed').onchange=()=>{dirty=true};
$('addBox').onclick=()=>{drawMode='add';$('editorStatus').textContent='Drag a box tightly around the new target.'};
$('redrawBox').onclick=()=>{drawMode='replace';$('editorStatus').textContent='Drag a corrected box around the selected target.'};
$('removeBox').onclick=()=>{if(selected>=0){draft.splice(selected,1);$('boxesConfirmed').checked=false;selected=draft.length?Math.min(selected,draft.length-1):-1;dirty=true;targetControls();draw()}};
$('noObject').onclick=()=>{draft=[];selected=-1;dirty=true;$('boxesConfirmed').checked=false;drawMode=null;targetControls();draw();$('editorStatus').textContent='Marked as no object. Confirm the training checkbox if this is a useful negative example.'};
function point(event){const r=canvas.getBoundingClientRect();return {x:Math.max(0,Math.min(canvas.width,(event.clientX-r.left)/r.width*canvas.width)),y:Math.max(0,Math.min(canvas.height,(event.clientY-r.top)/r.height*canvas.height))}}
canvas.addEventListener('pointerdown',event=>{
 if(loading||!image)return;event.preventDefault();const p=point(event);
 if(drawMode){start=p;canvas.setPointerCapture(event.pointerId);return}
 const hits=draft.map((r,i)=>({r,i})).filter(({r})=>{if(r.object==='cloud')return false;const b=displayBounds(r);return p.x>=b.left&&p.x<=b.right&&p.y>=b.top&&p.y<=b.bottom});if(hits.length){selected=hits.sort((a,b)=>(a.r.bounds.right-a.r.bounds.left)*(a.r.bounds.bottom-a.r.bounds.top)-(b.r.bounds.right-b.r.bounds.left)*(b.r.bounds.bottom-b.r.bounds.top))[0].i;targetControls();draw()}
});
canvas.addEventListener('pointermove',event=>{if(!start)return;const p=point(event);drawing={left:Math.min(start.x,p.x),top:Math.min(start.y,p.y),right:Math.max(start.x,p.x),bottom:Math.max(start.y,p.y)};draw()});
canvas.addEventListener('pointerup',event=>{
 if(!start)return;const p=point(event),b={left:Math.min(start.x,p.x),top:Math.min(start.y,p.y),right:Math.max(start.x,p.x),bottom:Math.max(start.y,p.y)};
 if(b.right-b.left>=1&&b.bottom-b.top>=1){if(drawMode==='add'){draft.push({bounds:b,object:'unknown',shape:'unresolved'});selected=draft.length-1}else if(selected>=0)draft[selected].bounds=b;dirty=true;$('boxesConfirmed').checked=false;$('editorStatus').textContent='Box updated. Check its object and shape labels.'}
 start=null;drawing=null;drawMode=null;targetControls();draw();if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);
});
canvas.addEventListener('pointercancel',()=>{start=null;drawing=null;drawMode=null;draw()});
async function save(){
 if(!saveAllowed())return;
 loading=true;targetControls();$('editorStatus').textContent='Saving correction…';
 try{
  const key=detail.key;
  await api('/api/boxed-review/save',{key,regions:draft,no_object:!draft.length,boxes_confirmed:$('boxesConfirmed').checked,note:$('reviewNote').value});
  visited.add(key);saved++;dirty=false;await nextFrame();
 }catch(e){loading=false;$('editorStatus').textContent=e.message;targetControls()}
}
async function skip(){
 if(loading||!detail)return;
 if(dirty&&!confirm('Skip this frame without saving your changes?'))return;
 visited.add(detail.key);skipped++;dirty=false;await nextFrame();
}
$('saveNext').onclick=save;$('skipFrame').onclick=skip;
$('restartPass').onclick=()=>{visited.clear();skipped=0;nextFrame()};
$('openBoxed').onclick=event=>{event.preventDefault();if(detail)window.open(detail.boxed_url+'&v='+Date.now(),'_blank','noopener')};
for(const id of ['filterObject','filterReview'])$(id).onchange=resetPass;
let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(resetPass,300)};
let videoTimer,videoSpec=null;
function resetSourceVideo(){
 clearTimeout(videoTimer);const player=$('sourceVideo');player.pause();player.removeAttribute('src');player.load();player.hidden=true;
 $('jumpToEvent').hidden=true;$('verificationPanel').open=false;videoSpec=detail?.video||null;
 $('videoStatus').textContent=videoSpec?.description||'Video details will appear when this frame loads.';
 $('playSource').textContent='Play source video';$('playSource').disabled=!videoSpec||(!videoSpec.available&&!videoSpec.can_prepare);
 $('externalVideo').hidden=!videoSpec?.watch_url;if(videoSpec?.watch_url)$('externalVideo').href=videoSpec.watch_url;
}
function showSourceVideo(spec){
 videoSpec=spec;const player=$('sourceVideo');$('videoStatus').textContent=spec.description+' · jump near event';$('verificationPanel').open=true;
 player.hidden=false;$('jumpToEvent').hidden=false;$('playSource').disabled=false;$('playSource').textContent='Play source video';
 if(player.getAttribute('src')!==spec.url){player.src=spec.url;player.addEventListener('loadedmetadata',()=>{if(player.getAttribute('src')!==spec.url)return;player.currentTime=Math.max(0,Math.min(spec.event_seconds||0,Number.isFinite(player.duration)?Math.max(0,player.duration-.1):spec.event_seconds||0))},{once:true});player.load()}
 player.play().catch(()=>{$('videoStatus').textContent=spec.description+' · tap Play to start'});
}
async function pollSourceVideo(key,generation=navigation){
 try{const spec=await api('/api/boxed-review/video-status?key='+encodeURIComponent(key));if(detail?.key!==key||generation!==navigation)return;
  if(spec.available){showSourceVideo(spec);return}
  $('videoStatus').textContent=spec.error||'Preparing a short event preview on the station…';
  if(spec.state==='failed'){$('playSource').disabled=false;return}
  videoTimer=setTimeout(()=>pollSourceVideo(key,generation),2000);
 }catch(e){if(detail?.key===key){$('videoStatus').textContent=e.message;$('playSource').disabled=false}}
}
$('playSource').onclick=async()=>{
 if(!detail||loading)return;const key=detail.key,generation=navigation;
 if(videoSpec?.available){showSourceVideo(videoSpec);return}
 $('playSource').disabled=true;$('videoStatus').textContent='Preparing a short event preview…';
 try{const spec=await api('/api/boxed-review/video',{key});if(detail?.key!==key||generation!==navigation)return;if(spec.available)showSourceVideo(spec);else pollSourceVideo(key,generation)}catch(e){$('videoStatus').textContent=e.message;$('playSource').disabled=false}
};
$('jumpToEvent').onclick=()=>{const player=$('sourceVideo');if(videoSpec)player.currentTime=Math.max(0,Math.min(videoSpec.event_seconds||0,Number.isFinite(player.duration)?Math.max(0,player.duration-.1):videoSpec.event_seconds||0))};
$('sourceVideo').addEventListener('error',()=>{if($('sourceVideo').getAttribute('src')){$('videoStatus').textContent='Video could not load. You can retry Play source video.';$('playSource').disabled=false}});

nextFrame();

$('targetDetail').addEventListener('error',()=>{$('targetDetail').hidden=true;$('targetZoom').hidden=false;$('detailCaption').textContent='Smoothed preview · saved crop unavailable';});

function renderTraining(state){
 const names={idle:'READY',queued:'QUEUED',building_dataset:'PREPARING',uploading:'PREPARING',initializing:'STARTING',extracting_features:'LEARNING',training:'LEARNING',exporting:'CHECKING',calibrating:'CHECKING',evaluating:'TESTING',candidate_ready:'TESTING',deploying:'DEPLOYING',deployed:'ACTIVE',rejected:'NEEDS MORE EXAMPLES',failed:'TRAINING FAILED',waiting_for_data:'NEEDS MORE EXAMPLES'};
 const active=state.active_model||{};
 $('activeModel').textContent=(active.name||'Original detector')+' · '+(active.version||'baseline-yolov3');
 $('trainingPhase').textContent=names[state.phase]||state.phase;
 $('trainingMessage').textContent=state.error||state.message||'';
 $('trainingProgress').hidden=!state.busy;$('trainingProgress').value=state.progress||0;
 $('trainNow').disabled=state.busy||state.request_pending;
 if(document.activeElement!==$('autoTrain'))$('autoTrain').checked=!!state.configuration?.auto_enabled;
 $('trainingCounts').textContent=`${state.confirmed_reviews} confirmed frames · ${state.new_reviews} new or changed since last run. Automatic batches: ${state.configuration?.min_new_reviews} new reviews, at least ${Math.round((state.configuration?.min_interval_seconds||1800)/60)} minutes apart.`;
 const report=state.report||active.report;
 $('trainingMetrics').textContent=report?`Held-out test: precision ${Math.round(report.candidate.precision*100)}% · bird/airplane F1 ${Math.round(report.candidate.macro_f1*100)}% (previous ${Math.round(report.baseline.macro_f1*100)}%). ${report.session_counts?.test||0} test recording sessions. Birds: ${report.candidate.bird.tp}/${report.candidate.bird.tp+report.candidate.bird.fn} (previous ${report.baseline.bird.tp}). Airplanes: ${report.candidate.airplane.tp}/${report.candidate.airplane.tp+report.candidate.airplane.fn} (previous ${report.baseline.airplane.tp}). Small pilot dataset; suggestions still need review.`:'';
}
async function refreshTraining(){try{renderTraining(await api('/api/model-training/status'))}catch(e){$('trainingMessage').textContent='Training status unavailable'}finally{setTimeout(refreshTraining,5000)}}
$('trainNow').onclick=async()=>{try{renderTraining(await api('/api/model-training/start',{}))}catch(e){$('trainingMessage').textContent=e.message}};
$('autoTrain').onchange=async()=>{try{renderTraining(await api('/api/model-training/configure',{auto_enabled:$('autoTrain').checked}))}catch(e){$('trainingMessage').textContent=e.message}};
refreshTraining();
