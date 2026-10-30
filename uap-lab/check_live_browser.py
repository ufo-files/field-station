"""Check real live preview and short manual Start/Stop recording without changing triggers."""
import json,time,subprocess,urllib.request

def req(url,data=None,method=None):
 r=urllib.request.Request(url,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
 return json.load(urllib.request.urlopen(r,timeout=40))
station=req('http://localhost:8090/api/session')
if station.get('active'):raise SystemExit('Manual recording check deferred: an existing session is active; preserving it.')
p=subprocess.Popen(['chromedriver','--port=9519'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);wd=None;created=None
try:
 time.sleep(1);s=req('http://localhost:9519/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'args':['--headless=new','--no-sandbox','--disable-dev-shm-usage'],'mobileEmulation':{'deviceMetrics':{'width':820,'height':1180,'pixelRatio':1,'touch':True}}}}}});wd='http://localhost:9519/session/'+s['value']['sessionId']
 def js(code):return req(wd+'/execute/sync',{'script':code,'args':[]})['value']
 def until(code):
  for _ in range(100):
   if js(code):return
   time.sleep(.25)
  raise AssertionError('Timed out: '+code)
 req(wd+'/url',{'url':'http://localhost:8091/'});until('return !!state');js('document.getElementById("liveTab").click()');until('return document.getElementById("liveImage").naturalWidth>0&&!!sessionState')
 assert js('return !document.getElementById("startSession").disabled');assert js('return document.getElementById("stopSession").disabled')
 first=js('return liveState.frame_epoch');time.sleep(1);until('return liveState.frame_epoch>'+str(first));assert js('return Date.now()/1000-liveState.frame_epoch<3')
 js('document.getElementById("startSession").click()');until('return !!sessionState.active');created=js('return sessionState.active.id');assert js('return !document.getElementById("stopSession").disabled');time.sleep(3)
 js('document.getElementById("stopSession").click()');until('return !sessionState.active&&!sessionBusy');assert js('return !document.getElementById("startSession").disabled')
 from pathlib import Path
 folder=Path('/home/hackrf/t7/sessions')/created;manifest=json.loads((folder/'manifest.json').read_text());assert manifest['capture_origin']=='manual';assert manifest['state']!='recording';assert (folder/'rf.jsonl').stat().st_size>0
 final=req('http://localhost:8090/api/session');assert not any(final['triggers'].values());assert not final['active']
 print('PASS: iPad-sized live preview updates while model inference runs; Start/Stop buttons record and stop manual session '+created+'; RF logs saved; motion/RF/scheduled triggers remain disabled.')
finally:
 if created:
  current=req('http://localhost:8090/api/session')
  if (current.get('active') or {}).get('id')==created:
   r=urllib.request.Request('http://localhost:8090/api/stop',data=json.dumps(dict(expected_session_id=created)).encode(),headers={'Content-Type':'application/json','X-Station-Token':current['csrf']});urllib.request.urlopen(r,timeout=90).read()
 if wd:req(wd,method='DELETE')
 p.terminate();p.wait()
