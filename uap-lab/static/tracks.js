'use strict';
const node=id=>document.getElementById(id);let rows=[],token='',category='',current=null;const selected=new Set();let selectedVideo=null;
async function request(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;}
function message(text){node('trackMessage').textContent=text;}
const categoryNames={telephone_pole:'Telephone poles',house:'Houses',antenna:'Antennas',vehicle:'Vehicles',pursue:'PURSUE',anomalous_field_station:'Anomalous – Field Station',anomalous:'Anomalous',airplane:'Airplanes',star:'Stars',satellite:'Satellites',shooting_star:'Shooting stars',cloud:'Clouds',bird:'Birds',insect:'Insects',drone:'Drones',tree:'Trees',balloon:'Balloons',other_animal:'Other animals'};
let total=0,offset=0,loading=false,revision=0;
async function refresh(){token=(await request('/api/labeled-frames/token')).token;await load();}
async function load(){
 revision++;rows=[];offset=0;total=0;loading=false;node('observations').replaceChildren();node('loadMore').hidden=true;
 await nextPage(revision);
}
async function nextPage(version=revision){
 if(loading)return;loading=true;node('loadMore').disabled=true;
 try{
 const q=new URLSearchParams({limit:100,offset,label:category,search:node('trackSearch').value.trim(),video:node('trackVideo').value});
 const page=await request('/api/labeled-frames?'+q);if(version!==revision)return;
 total=page.total;offset+=page.items.length;rows.push(...page.items);
 const previous=node('trackVideo').value;node('trackVideo').replaceChildren(new Option('All videos and reviews',''));
 for(const [id,name]of Object.entries(page.videos||{}))node('trackVideo').append(new Option(name,id));node('trackVideo').value=previous;
 const labels=Object.entries(page.labels||{}),counts=[...labels,['anomalous_field_station',page.groups?.anomalous_field_station||0],['pursue',page.groups?.pursue||0]];node('categoryTabs').replaceChildren();
 for(const [key,count]of [['',labels.reduce((sum,p)=>sum+p[1],0)],...counts.sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))]){const button=document.createElement('button');button.type='button';button.textContent=(key?(categoryNames[key]||key.replaceAll('_',' ')):'All')+' ('+count+')';button.setAttribute('aria-pressed',String(category===key));button.onclick=()=>{category=key;load();};node('categoryTabs').append(button);}
 for(const row of page.items){const card=document.createElement('article');card.className='track-observation';const button=document.createElement('button');button.className='track-image';button.type='button';button.title='Inspect labeled object';const img=document.createElement('img');img.width=320;img.height=320;img.style.aspectRatio='auto 1 / 1';img.src=row.image_url;img.loading='lazy';img.decoding='async';img.alt=row.annotation.label+' · '+row.source_name+' · '+row.video_name;button.append(img);button.onclick=()=>inspect(row);card.append(button);node('observations').append(card);}
 message(rows.length+' of '+total+' labeled objects');node('loadMore').hidden=offset>=total;
 }catch(e){if(version===revision){message(e.message);node('loadMore').hidden=false;}}
 finally{if(version===revision){loading=false;node('loadMore').disabled=false;}}
}
node('loadMore').onclick=()=>nextPage();
const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&offset>0&&offset<total)nextPage();},{rootMargin:'200px'});observer.observe(node('loadMore'));
function inspect(row){
 current=row;const a=row.annotation;node('frameHeading').textContent=a.label+' · '+row.video_name;node('frameDetails').textContent=row.source_name+' · '+Number(a.time||0).toFixed(3)+' s'+(row.excluded?' · Excluded from multiclass training':'');
 const canFrame=row.kind==='video'&&row.original_available;node('frameBox').hidden=true;node('frameStatus').textContent=canFrame?'Loading original frame…':'Saved object crop';node('nativeFrame').removeAttribute('src');
 node('nativeFrame').onload=()=>{if(current!==row)return;node('frameStatus').textContent=canFrame?'Original frame':row.kind==='preserved'?'Saved object crop. Original video is not available in the preserved library.':'Saved object crop. Open the review video to inspect surrounding frames.';if(canFrame&&a.bounds){const b=a.bounds;Object.assign(node('frameBox').style,{left:b.x*100+'%',top:b.y*100+'%',width:b.w*100+'%',height:b.h*100+'%'});node('frameBox').hidden=false;}};
 node('nativeFrame').onerror=()=>{node('frameStatus').textContent='Image could not be loaded.';};node('nativeFrame').src=canFrame?'/api/frame?id='+encodeURIComponent(row.video_id)+'&time='+a.time:row.image_url;
 node('selectObservation').hidden=row.kind!=='video';node('selectObservation').textContent=selectedVideo===row.video_id&&selected.has(a.id)?'Deselect observation':'Select observation for linking';
 node('linkTrack').hidden=row.kind!=='video';node('linkTrack').disabled=selected.size<2;node('selectionStatus').textContent=selected.size?selected.size+' observations selected from one video.':'';
 node('removeLabel').hidden=row.kind!=='video';node('removeLabel').disabled=false;
 const link=row.review_url||row.source_page;node('reviewLink').hidden=!link;node('reviewLink').textContent=row.review_url?'Open review video':'Original source page';node('reviewLink').href=link&&(/^(https?:\/\/|\/email-review\?)/.test(link))?link:'#';
 if(!node('frameViewer').open)node('frameViewer').showModal();
}
node('selectObservation').onclick=()=>{const r=current;if(r.kind!=='video')return;if(selected.has(r.annotation.id)&&selectedVideo===r.video_id)selected.delete(r.annotation.id);else{if(selectedVideo&&selectedVideo!==r.video_id){node('selectionStatus').textContent='Choose observations from the same video to link a track.';return;}selectedVideo=r.video_id;selected.add(r.annotation.id);}if(!selected.size)selectedVideo=null;inspect(r);};
node('removeLabel').onclick=async()=>{const r=current;if(r.kind!=='video'||!confirm('Remove this '+r.annotation.label+' label? The recording will require review again. Saved models and original footage remain.'))return;node('removeLabel').disabled=true;try{await request('/api/delete-annotation',{id:r.video_id,annotation:r.annotation.id});selected.delete(r.annotation.id);if(!selected.size)selectedVideo=null;node('frameViewer').close();await refresh();message('Label removed. Recording requires review again; saved models are unchanged.');}catch(e){node('frameStatus').textContent=e.message;node('removeLabel').disabled=false;}};
node('linkTrack').onclick=async()=>{node('linkTrack').disabled=true;node('selectionStatus').textContent='Saving track and updating model…';try{const result=await request('/api/tracks/link',{id:selectedVideo,annotations:[...selected],train:true});selected.clear();selectedVideo=null;await refresh();node('frameViewer').close();message(result.training_error?'Track saved; model update failed: '+result.training_error:result.observations+' observations linked. Model updated.');}catch(e){node('selectionStatus').textContent=e.message;node('linkTrack').disabled=selected.size<2;}};
node('trackVideo').onchange=()=>{category='';load();};let searchTimer;node('trackSearch').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(load,200);};node('closeFrame').onclick=()=>node('frameViewer').close();
const requested=new URLSearchParams(location.search).get('video');if(requested){node('trackVideo').append(new Option(requested,'video:'+requested));node('trackVideo').value='video:'+requested;}refresh().catch(e=>message(e.message));
window.addEventListener('station-reconnected',e=>{token=e.detail.token;if(!rows.length)load();});
