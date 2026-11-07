'use strict';
(()=>{
 const row=document.getElementById('ce5Control'),toggle=document.getElementById('ce5Toggle');
 if(!row||window.FIELD_PUBLIC_READ_ONLY===true)return;
 row.hidden=false;let polling=false,busy=false,playing=false,lastError='';
 function render(state){playing=state.playing===true;toggle.checked=playing;toggle.disabled=busy||!state.available;toggle.title=state.error||(state.available?'Play '+state.track+' through the field station audio output':'Downloaded CE5 audio is not available on the station yet.');if(state.error&&state.error!==lastError)notice(state.error,true);lastError=state.error||'';}
 async function poll(){if(polling||busy||document.hidden)return;polling=true;try{const state=await api('/api/ce5',undefined,5000);if(!busy)render(state);}catch{toggle.title='Waiting for station audio status';}finally{polling=false;}}
 toggle.onchange=async()=>{if(busy)return;const enabled=toggle.checked;busy=true;toggle.disabled=true;try{render(await api('/api/ce5',{enabled}));}catch(e){toggle.checked=playing;notice(e.message,true);}finally{busy=false;await poll();}};
 void poll();setInterval(poll,3000);
})();
