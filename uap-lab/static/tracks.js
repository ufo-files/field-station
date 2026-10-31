'use strict';
const node=id=>document.getElementById(id);let rows=[],token='',category='',current=null;const selected=new Set();let selectedVideo=null;
async function request(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;}
function message(text){node('trackMessage').textContent=text;}
const categoryNames={anomalous:'Anomalous',airplane:'Airplanes',star:'Stars',satellite:'Satellites',shooting_star:'Shooting stars',cloud:'Clouds',bird:'Birds',insect:'Insects',drone:'Drones',tree:'Trees',balloon:'Balloons',other_animal:'Other animals'};
async function refresh(){
 token=(await request('/api/labeled-frames/token')).token;const items=[];let offset=0;
 while(true){const page=await request('/api/labeled-frames?limit=96&offset='+offset);items.push(...page.items);offset+=page.items.length;if(offset>=page.total||!page.items.length)break;}
 rows=items;const previous=node('trackVideo').value;node('trackVideo').replaceChildren(new Option('All videos and reviews',''));
 const videos=new Map(rows.map(r=>[r.kind+':'+r.video_id,r.video_name]));for(const [id,name]of videos)node('trackVideo').append(new Option(name,id));node('trackVideo').value=videos.has(previous)?previous:'';
 for(const id of [...selected])if(!rows.some(r=>r.kind==='video'&&r.video_id===selectedVideo&&r.annotation.id===id))selected.delete(id);if(!selected.size)selectedVideo=null;load();
}
function load(){
 const search=node('trackSearch').value.trim().toLowerCase(),video=node('trackVideo').value;
 const filtered=rows.filter(r=>(!video||r.kind+':'+r.video_id===video)&&[r.video_name,r.video_id,r.source_name].join(' ').toLowerCase().includes(search));
 const counts=new Map();for(const r of filtered)counts.set(r.annotation.label,(counts.get(r.annotation.label)||0)+1);
 node('categoryTabs').replaceChildren();for(const [key,count]of [['',filtered.length],...[...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))]){const button=document.createElement('button');button.type='button';button.textContent=(key?(categoryNames[key]||key.replaceAll('_',' ')):'All')+' ('+count+')';button.setAttribute('aria-pressed',String(category===key));button.onclick=()=>{category=key;load();};node('categoryTabs').append(button);}
 node('observations').replaceChildren();let count=0;for(const row of filtered){if(category&&row.annotation.label!==category)continue;count++;const card=document.createElement('article');card.className='track-observation';const button=document.createElement('button');button.className='track-image';button.type='button';button.title='Inspect labeled object';const img=document.createElement('img');img.src=row.image_url;img.loading='lazy';img.decoding='async';img.alt=row.annotation.label+' · '+row.source_name+' · '+row.video_name;button.append(img);button.onclick=()=>inspect(row);card.append(button);node('observations').append(card);}
 message(count+' labeled objects'+(selected.size?' · '+selected.size+' selected for linking':''));
}
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
node('removeLabel').onclick=async()=>{const r=current;if(r.kind!=='video'||!confirm('Remove this '+r.annotation.label+' label? The recording will require review again. Saved models and original footage remain.'))return;node('removeLabel').disabled=true;try{await request('/api/delete-annotation',{id:r.video_id,annotation:r.annotation.id});node('frameViewer').close();await refresh();message('Label removed. Recording requires review again; saved models are unchanged.');}catch(e){node('frameStatus').textContent=e.message;node('removeLabel').disabled=false;}};
node('linkTrack').onclick=async()=>{node('linkTrack').disabled=true;node('selectionStatus').textContent='Saving track and updating model…';try{const result=await request('/api/tracks/link',{id:selectedVideo,annotations:[...selected],train:true});selected.clear();selectedVideo=null;await refresh();node('frameViewer').close();message(result.training_error?'Track saved; model update failed: '+result.training_error:result.observations+' observations linked. Model updated.');}catch(e){node('selectionStatus').textContent=e.message;node('linkTrack').disabled=selected.size<2;}};
node('trackVideo').onchange=()=>{category='';load();};node('trackSearch').oninput=load;node('closeFrame').onclick=()=>node('frameViewer').close();
refresh().then(()=>{const requested=new URLSearchParams(location.search).get('video');if(rows.some(r=>r.video_id===requested)){node('trackVideo').value='video:'+requested;load();}}).catch(e=>message(e.message));
