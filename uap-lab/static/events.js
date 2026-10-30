'use strict';
const rendered=new Map();
function artifact(id,name){return '/api/live/artifact?session='+encodeURIComponent(id)+'&name='+encodeURIComponent(name)}
function eventLink(text,url){const a=document.createElement('a');a.textContent=text;a.href=url;return a}
async function refreshEvents(){try{
 const responses=await Promise.all(['/api/live/status','/api/live/session','/api/provisional'].map(async url=>{const r=await fetch(url);if(!r.ok)throw Error('Videos unavailable');return r.json()}));
 const records=new Map();for(const event of [...(responses[0].events||[]),...(responses[1].recent_manual||[]),...(responses[2].jobs||[]).map(j=>({...j,kind:'provisional',created:j.created}))])if(!records.has(event.session_id))records.set(event.session_id,event);
 for(const event of [...records.values()].sort((a,b)=>a.created-b.created)){
  if(rendered.has(event.session_id)){const previous=rendered.get(event.session_id);if(previous.queueStatus)previous.queueStatus.textContent='Classification: '+(event.classification||'unclassified')+' · '+(event.state||'pending');await updateAvailability(previous,event.session_id);continue;}
  const card=document.createElement('article');card.className='event-card';
  const heading=document.createElement('h2');heading.textContent=(event.kind==='manual'?'Manual recording':event.kind==='provisional'?'Provisional motion':'Model anomaly match')+' · '+new Date(event.created*1000).toLocaleString();
  const video=document.createElement('video');video.controls=true;video.playsInline=true;video.preload='none';video.hidden=true;video.setAttribute('aria-label',heading.textContent);
  const links=document.createElement('p');card.video=video;card.links=links;card.availability=document.createElement('p');card.availability.setAttribute('role','status');card.availability.textContent='Checking video…';
  card.append(heading);if(event.kind==='provisional'){const status=document.createElement('p');status.textContent='Classification: '+(event.classification||'unclassified')+' · '+(event.state||'pending');card.queueStatus=status;card.append(status);}card.append(card.availability,video,links);document.getElementById('eventVideos').prepend(card);rendered.set(event.session_id,card);await updateAvailability(card,event.session_id);
 }
 document.getElementById('eventStatus').textContent=records.size?'Saved videos appear here when recording finishes.':'No recent saved events.';
}catch(error){document.getElementById('eventStatus').textContent=error.message+'. Retrying…';}}
refreshEvents();setInterval(refreshEvents,10000);

async function updateAvailability(card,id){
 try{
  const response=await fetch('/api/live/artifact-status?session='+encodeURIComponent(id));if(!response.ok)throw Error('Status unavailable');const status=await response.json();
  if(status.available['video.mp4']){if(!card.video.src)card.video.src=artifact(id,'video.mp4');card.video.hidden=false;card.availability.textContent='Ready to play';}
  else{card.availability.textContent=status.state==='recording'?'Recording… Video will be available after it stops.':status.playback==='failed'?'Playback preparation failed; original footage is retained.':'Preparing video… This page updates automatically.';}
  card.links.replaceChildren();
  if(status.available['video.mp4'])card.links.append(eventLink('Play video',artifact(id,'video.mp4')));
  if(status.available['video.mkv'])card.links.append(eventLink('Original video',artifact(id,'video.mkv')));
  if(status.available['rf.jsonl'])card.links.append(eventLink('RF log',artifact(id,'rf.jsonl')));
 }catch{card.availability.textContent='Checking video availability…';}
}
