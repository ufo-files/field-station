'use strict';
const node=id=>document.getElementById(id);let library,token,selectedVideo=null,category="";const selected=new Set();
async function request(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':token},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;}
function message(text){node('trackMessage').textContent=text;}
const categoryNames={anomalous:'Anomalous',airplane:'Airplanes',star:'Stars',satellite:'Satellites',shooting_star:'Shooting stars',cloud:'Clouds',bird:'Birds',insect:'Insects',drone:'Drones',tree:'Trees',balloon:'Balloons',other_animal:'Other animals'};
function categories(videos){
 const counts=new Map((library.labels||[]).map(label=>[label,0]));for(const v of videos)for(const p of v.annotations)counts.set(p.label,(counts.get(p.label)||0)+1);
 node('categoryTabs').replaceChildren();
 for(const [key,count] of [['', [...counts.values()].reduce((a,b)=>a+b,0)],...Array.from(counts).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))]){
  const button=document.createElement('button');button.type='button';button.textContent=(key?(categoryNames[key]||key.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase())):'All')+' ('+count+')';button.setAttribute('aria-pressed',String(category===key));button.onclick=()=>{category=key;load();};node('categoryTabs').append(button);
 }
}
function load(){
 selected.clear();selectedVideo=null;node('linkTrack').disabled=true;node('observations').replaceChildren();
 const videos=library.videos.filter(v=>v.annotations?.length&&(!node('trackVideo').value||v.id===node('trackVideo').value));let count=0,trackCount=0,videoCount=0;categories(videos);
 for(const video of videos){
  const points=video.annotations.filter(p=>!category||p.label===category);if(!points.length)continue;videoCount++;const tracks=new Map();for(const point of video.annotations){if(!tracks.has(point.track_id||point.id))tracks.set(point.track_id||point.id,tracks.size+1);}trackCount+=new Set(points.map(p=>p.track_id||p.id)).size;
  for(const point of [...points].sort((a,b)=>a.time-b.time)){
   count++;const row=document.createElement('article');row.className='track-observation';
   const show=document.createElement('button');show.className='track-image';show.type='button';show.title='View original frame';
   const image=document.createElement('img');image.src='/api/annotation?id='+encodeURIComponent(video.id)+'&annotation='+encodeURIComponent(point.id);image.alt=point.label+' · Object '+tracks.get(point.track_id||point.id)+' at '+point.time.toFixed(3)+' seconds · '+video.name;image.loading='lazy';image.decoding='async';show.append(image);
   show.onclick=()=>{node('frameHeading').textContent=video.name+' · '+point.label+' · '+point.time.toFixed(3)+' s';node('nativeFrame').src='/api/frame?id='+encodeURIComponent(video.id)+'&time='+point.time;node('frameViewer').showModal();};
   const details=document.createElement('div');details.className='track-details';const label=document.createElement('label');const input=document.createElement('input');input.type='checkbox';input.value=point.id;
   input.onchange=()=>{if(input.checked&&selectedVideo&&selectedVideo!==video.id){input.checked=false;message('Choose observations from the same video to link a track.');return;}if(input.checked){selectedVideo=video.id;selected.add(point.id);}else selected.delete(point.id);if(!selected.size)selectedVideo=null;node('linkTrack').disabled=selected.size<2;message(selected.size+' observations selected. Confirm they show the same object.');};
   const caption=document.createElement('span');caption.textContent=point.label+' · Object '+tracks.get(point.track_id||point.id);label.append(input,caption);
   const source=document.createElement('p');source.className='track-source';source.textContent=video.name+' · '+point.time.toFixed(3)+' s';
   const review=document.createElement('button');review.type='button';review.textContent='Show video tracks';review.onclick=()=>{node('trackVideo').value=video.id;load();};
   details.append(label,source,review);row.append(show,details);node('observations').append(row);
  }
 }
 message(count?count+' observations · '+trackCount+' tracks · '+videoCount+' videos':'No saved observations match this filter.');
}
node('trackVideo').onchange=()=>{category='';load();};
node('closeFrame').onclick=()=>node('frameViewer').close();
node('linkTrack').onclick=async()=>{node('linkTrack').disabled=true;message('Saving the confirmed track and updating the model…');try{const result=await request('/api/tracks/link',{id:selectedVideo,annotations:[...selected],train:true});library=await request('/api/state');token=library.token;load();message(result.training_error?'Track saved; model update failed: '+result.training_error:result.observations+' observations linked. Model updated; '+(result.temporal_windows||0)+' temporal training windows. GitHub publication is queued.');}catch(e){message(e.message);node('linkTrack').disabled=selected.size<2;}};
(async()=>{library=await request('/api/state');token=library.token;const videos=library.videos.filter(v=>v.annotations?.length);for(const video of videos){const option=document.createElement('option');option.value=video.id;option.textContent=video.name;node('trackVideo').append(option);}const requested=new URLSearchParams(location.search).get('video');if(videos.some(v=>v.id===requested))node('trackVideo').value=requested;load();})().catch(e=>message(e.message));
