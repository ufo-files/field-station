"""Read-only iPad browser check of fullscreen, stable Live status, and model overlays."""
import json,time,subprocess,urllib.request

def req(url,data=None,method=None):
 r=urllib.request.Request(url,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
 return json.load(urllib.request.urlopen(r,timeout=45))
p=subprocess.Popen(['chromedriver','--port=9520'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);wd=None
try:
 time.sleep(1);s=req('http://localhost:9520/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'args':['--headless=new','--no-sandbox','--disable-dev-shm-usage'],'mobileEmulation':{'deviceMetrics':{'width':820,'height':1180,'pixelRatio':1,'touch':True}}},'goog:loggingPrefs':{'browser':'ALL'}}}});wd='http://localhost:9520/session/'+s['value']['sessionId']
 def js(code):return req(wd+'/execute/sync',{'script':code,'args':[]})['value']
 def until(code):
  for _ in range(100):
   if js(code):return
   time.sleep(.25)
  raise AssertionError('Timed out: '+code)
 req(wd+'/url',{'url':'http://localhost:8091/'});until('return !!state');js('document.getElementById("liveTab").click()');until('return document.getElementById("liveImage").naturalWidth>0&&!!liveState')
 assert js('return !document.getElementById("liveToggle")');assert js('return document.querySelector("#liveScreen h2")===null')
 # Change only responses inside this browser. No recording/model settings are written.
 js('window.actualApi=api;window.flip=0;api=async(path,...args)=>{if(path==="/api/live/status")return {...liveState,phase:(++window.flip%2?"analyzing":"tagging"),frame_epoch:Date.now()/1000,inference_epoch:Date.now()/1000,width:1920,height:1080,error:null,preview_error:null,objects:[{box:[100,100,200,150],label:"anomalous",score:.99,target_id:1,confirmed:true},{box:[700,400,120,90],label:"anomalous",score:.98,target_id:2,confirmed:false}]};if(path==="/api/live/session")return {active:{id:"presentation-only",rf_records:3},recent_manual:[]};return actualApi(path,...args)};pollLive()')
 until('return document.getElementById("liveRecordingBadge").hidden===false');time.sleep(1)
 assert js('return document.getElementById("liveStatus").textContent.trim()==="Live"');assert js('return document.getElementById("liveStatus").dataset.state==="live"')
 def boxes_visible():
  return js('const c=document.getElementById("liveBoxes"),ctx=c.getContext("2d");return [[100,175],[700,445]].every(([x,y])=>{const a=ctx.getImageData(Math.round(x*c.width/1920)-2,Math.round(y*c.height/1080)-2,5,5).data;return [...a].some((v,i)=>i%4===3&&v>0)})')
 assert boxes_visible()
 # Exercise iPad fallback explicitly; it must preserve the overlay and aspect ratio.
 js('document.getElementById("liveViewer").requestFullscreen=()=>Promise.reject(new Error("Fallback test"));document.getElementById("liveFullscreen").click()')
 until('return liveIsFullscreen()');assert js('const r=liveViewer.getBoundingClientRect();return Math.abs(r.width-innerWidth)<2&&Math.abs(r.height-innerHeight)<2')
 assert js('const s=liveStage.getBoundingClientRect(),i=document.getElementById("liveImage");return Math.abs(s.width/s.height-i.naturalWidth/i.naturalHeight)<.01')
 assert boxes_visible();time.sleep(5.5);assert js('return liveViewer.classList.contains("chrome-idle")');assert js('return getComputedStyle(document.querySelector(".live-chrome")).opacity==="0"');assert boxes_visible();assert js('return getComputedStyle(document.getElementById("liveRecordingBadge")).display!=="none"')
 js('liveViewer.dispatchEvent(new PointerEvent("pointerdown",{pointerType:"touch",bubbles:true}));');assert js('return !liveViewer.classList.contains("chrome-idle")')
 js('document.getElementById("liveFullscreen").click()');until('return !liveIsFullscreen()');assert js('return !document.body.classList.contains("live-fullscreen-open")')
 assert js('return document.documentElement.scrollWidth<=innerWidth')
 logs=req(wd+'/log',{'type':'browser'})['value'];errors=[v['message'] for v in logs if v['level']=='SEVERE' and 'favicon' not in v['message'] and 'Fullscreen request denied' not in v['message']];assert not errors,errors
 print('PASS: fullscreen iPad fallback fits image; two labeled model boxes stay aligned and visible after 5-second chrome fade; recording badge stays visible; touch restores controls; Live status stays stable; pause/heading removed; exit restores page.')
finally:
 if wd:req(wd,method='DELETE')
 p.terminate();p.wait()
