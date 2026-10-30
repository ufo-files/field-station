"""Isolated iPad-sized browser test: multiple targets, drafts, Next, Omit, Done."""
import base64,json,os,pathlib,shutil,subprocess,tempfile,time,urllib.request
APP=pathlib.Path(__file__).resolve().parent
root=pathlib.Path(tempfile.mkdtemp(prefix='uap-browser-'));inbox=root/'training-data';inbox.mkdir()
fixture='''import sys,cv2,numpy as np,lab
from pathlib import Path
root=Path(sys.argv[1]);frames=root/'frames';frames.mkdir();target=np.random.default_rng(42).integers(20,240,(16,16,3),dtype=np.uint8)
for i in range(15):
 im=np.full((128,256,3),12,np.uint8);im[20:36,20+i*2:36+i*2]=target;im[80:96,180-i*2:196-i*2]=target;cv2.imwrite(str(frames/f'{i:03d}.png'),im)
lab.run_command([lab.FFMPEG,'-v','error','-framerate','5','-i',str(frames/'%03d.png'),'-c:v','libx264','-crf','0','-threads','1','-pix_fmt','yuv420p','-y',str(root/'fixture.mp4')])
'''
subprocess.run([str(APP/'.venv/bin/python'),'-c',fixture,str(root)],cwd=APP,check=True,env=dict(os.environ,UAP_LAB_DATA=str(root/'fixture-data')))
shutil.copyfile(root/'fixture.mp4',inbox/'first.mp4');(inbox/'omit-me.mp4').write_bytes((root/'fixture.mp4').read_bytes()+b'different-training-input')
env=dict(os.environ,UAP_LAB_DATA=str(root/'data'),UAP_LAB_TRAINING_FOLDER=str(inbox),UAP_LAB_PORT='8092',UAP_LAB_LIVE='0',UAP_LAB_RESERVE_BYTES='0')
server=subprocess.Popen([str(APP/'.venv/bin/python'),'server.py'],cwd=APP,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
driver=subprocess.Popen(['chromedriver','--port=9518'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);wd=None

def req(url,data=None,method=None):
 r=urllib.request.Request(url,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
 return json.load(urllib.request.urlopen(r,timeout=60))
try:
 time.sleep(2)
 session=req('http://localhost:9518/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'args':['--headless=new','--no-sandbox','--disable-dev-shm-usage'],'mobileEmulation':{'deviceMetrics':{'width':820,'height':1180,'pixelRatio':1,'touch':True}}},'goog:loggingPrefs':{'browser':'ALL'}}}})
 wd='http://localhost:9518/session/'+session['value']['sessionId']
 def js(code):return req(wd+'/execute/sync',{'script':code,'args':[]})['value']
 def until(code):
  for _ in range(160):
   if js(code):return
   time.sleep(.3)
  raise AssertionError('Timed out: '+code)
 def draw_box(x,y,w,h,hold=0):
  js('canvas.scrollIntoView({block:"center"})')
  rect=js('return {x:canvas.getBoundingClientRect().left,y:canvas.getBoundingClientRect().top,w:canvas.getBoundingClientRect().width,h:canvas.getBoundingClientRect().height}')
  def point(a,b):return dict(x=round(rect['x']+rect['w']*a/256),y=round(rect['y']+rect['h']*b/128))
  req(wd+'/actions',{'actions':[{'type':'pointer','id':'finger','parameters':{'pointerType':'touch'},'actions':[dict(type='pointerMove',duration=0,origin='viewport',**point(x,y)),dict(type='pointerDown',button=0),dict(type='pause',duration=hold),dict(type='pointerMove',duration=200,origin='viewport',**point(x+w,y+h)),dict(type='pointerUp',button=0)]}]})
 req(wd+'/url',{'url':'http://localhost:8092/'});until('return !!state&&state.videos.length===2&&!!frozen');js('loadVideo(state.videos.find(v=>v.name==="first.mp4").id)');until('return !!frozen&&current.name==="first.mp4"')
 # A delayed native frame must never replace the image while the user holds a gesture.
 js('window.originalFetch=window.fetch;window.fetch=async(...args)=>{const r=await originalFetch(...args);if(String(args[0]).includes("/api/frame"))await new Promise(resolve=>setTimeout(resolve,700));return r};if(frozen)frozen.native=false;canvas.addEventListener("pointerdown",e=>{if(e.isPrimary!==false){window.dragImage=frozen.image;const id=activePointer;setTimeout(()=>{canvas.dispatchEvent(new PointerEvent("pointerdown",{pointerId:999,isPrimary:false,clientX:0,clientY:0}));window.secondaryIgnored=activePointer===id},100)} });capture()')
 draw_box(20,20,16,16,hold=1000);until('return drafts.length===1');assert js('return activePointer===null&&frozen.image===window.dragImage&&window.secondaryIgnored')
 js('window.fetch=window.originalFetch')
 # Two individual taps work without any drag/move events.
 def tap(x,y):
  rect=js('return {x:canvas.getBoundingClientRect().left,y:canvas.getBoundingClientRect().top,w:canvas.getBoundingClientRect().width,h:canvas.getBoundingClientRect().height}')
  req(wd+'/actions',{'actions':[{'type':'pointer','id':'finger','parameters':{'pointerType':'touch'},'actions':[dict(type='pointerMove',duration=0,origin='viewport',x=round(rect['x']+rect['w']*x/256),y=round(rect['y']+rect['h']*y/128)),dict(type='pointerDown',button=0),dict(type='pointerUp',button=0)]}]})
 tap(180,80);assert js('return !!corner&&drafts.length===1');tap(196,96);until('return drafts.length===2');assert js('return !corner');assert js('return document.querySelectorAll(".target-chip").length===2')
 js('document.getElementById("scrubber").value=.4;document.getElementById("scrubber").dispatchEvent(new Event("input"))');until('return !!frozen&&frozen.time>.39');draw_box(24,20,16,16);until('return drafts.length===3')
 js('document.getElementById("play").click()');until('return !video.paused');draw_box(24,20,16,16);until('return drafts.length===4');assert js('return video.paused');js('document.querySelectorAll(".target-chip")[3].lastElementChild.click()');until('return drafts.length===3')
 draw_box(248,110,10,20);until('return drafts.length===4');assert js('return drafts[3].bounds.x+drafts[3].bounds.w===1&&drafts[3].bounds.y+drafts[3].bounds.h===1');js('document.querySelectorAll(".target-chip")[3].lastElementChild.click()');until('return drafts.length===3')
 req(wd+'/refresh',{});until('return !!current&&drafts.length===3');assert js('return !document.getElementById("next").disabled');js('for(let i=0;i<8;i++)drafts.push({...drafts[0],id:newId()});persistDrafts();window.saveFetch=window.fetch;window.fetch=async(...args)=>{if(String(args[0])==="/api/review")await new Promise(resolve=>setTimeout(resolve,1200));return saveFetch(...args)};document.getElementById("next").click()');assert js('return busy&&document.getElementById("next").textContent.includes("Saving")');until('return current?.name==="omit-me.mp4"');assert js('return state.videos.find(v=>v.name==="first.mp4").annotations.length===11')
 js('window.fetch=window.saveFetch')
 omitted=js('return current.id');js('document.getElementById("omit").click()');until('return queue().length===0');assert (root/'data/videos'/omitted/'source').is_file();assert js('return state.videos.find(v=>v.id==="'+omitted+'").training_excluded')
 js('document.getElementById("done").click()');until('return !!state.model');assert js('return state.model.examples.length===11')
 req(wd+'/refresh',{});until('return !!state');assert js('return queue().length===0');assert js('return current===undefined||current===null')
 js('document.getElementById("testTab").click();document.getElementById("videos").value=state.videos.find(v=>v.name==="first.mp4").id;document.getElementById("test").click()');until('return state.runs.some(r=>["complete","failed"].includes(r.state))');result=req('http://localhost:8092/api/state')['runs'][0];assert result['state']=='complete',result;assert len(result['segments'][0]['crops'])==2,result
 assert js('return document.documentElement.scrollWidth<=innerWidth')
 logs=req(wd+'/log',{'type':'browser'})['value'];errors=[v['message'] for v in logs if v['level']=='SEVERE' and 'favicon' not in v['message']];assert not errors,errors
 # Renamed and copied input files must keep the existing review across server restart.
 renamed=inbox/'renamed-original.mp4';(inbox/'first.mp4').rename(renamed);shutil.copyfile(root/'fixture.mp4',inbox/'duplicate-copy.mp4')
 for _ in range(90):
  try:index=json.loads((root/'data/intake-index.json').read_text())
  except (OSError,ValueError):index={}
  if str(renamed.resolve()) in index and str((inbox/'duplicate-copy.mp4').resolve()) in index:break
  time.sleep(.3)
 else:raise AssertionError('Renamed/copy intake not indexed')
 assert len(list((root/'data/videos').glob('*/video.json')))==2
 server.terminate();server.wait();server=subprocess.Popen([str(APP/'.venv/bin/python'),'server.py'],cwd=APP,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(1)
 req(wd+'/refresh',{});until('return !!state&&state.videos.length===2');assert js('return queue().length===0');assert js('return !document.getElementById("doneScreen").hidden')
 print('PASS: delayed-frame touch drawing; two-tap corners; drawing pauses playback; automatic intake; two touch boxes in one frame; third selection at another time; draft reload; Next visibly saves 11 targets and advances; Omit persists without deleting source; Done trains; renamed/copied reviewed videos stay hidden across server restart; two target crops exported.')
finally:
 if wd:req(wd,method='DELETE')
 driver.terminate();driver.wait();server.terminate();server.wait()
