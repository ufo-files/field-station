"""Four Pacific-time sessions daily, preserving public replays and a local link ledger."""
import argparse,fcntl,json,subprocess,time,uuid
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

ZONE=ZoneInfo('America/Los_Angeles')
def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)
def slot(epoch):
 local=datetime.fromtimestamp(epoch,ZONE);start=local.replace(hour=local.hour//6*6,minute=0,second=0,microsecond=0);end=start+timedelta(hours=6)
 return dict(key=start.isoformat(),start=start.timestamp(),end=end.timestamp(),title='UFO-FILES.APP NETWORK | '+start.strftime('%b %d, %Y')+' | '+start.strftime('%H:%M')+'–'+end.strftime('%H:%M')+' Pacific')

class Studio:
 """Reuse the operator's signed-in Safari session; never export browser credentials."""
 def evaluate(self,js):
  script='tell application "Safari"\nset chosen to missing value\nrepeat with w in windows\nrepeat with t in tabs of w\nif URL of t contains "studio.youtube.com" and URL of t contains "livestreaming" then\nset chosen to t\nexit repeat\nend if\nend repeat\nif chosen is not missing value then exit repeat\nend repeat\nif chosen is missing value then error "Keep a signed-in YouTube Studio live dashboard tab open"\nreturn do JavaScript '+json.dumps(js)+' in chosen\nend tell'
  p=subprocess.run(['osascript','-e',script],capture_output=True,text=True,timeout=45)
  if p.returncode:raise RuntimeError('YouTube Studio session unavailable: '+p.stderr.strip()[:240])
  return p.stdout.strip()
 def post(self,path,body):
  key='__ufn_'+uuid.uuid4().hex
  js="""(()=>{const n=document.querySelector('ytls-apiary-network-manager');if(!n)throw Error('Open a YouTube live dashboard');const info={...n.SUPPORTED_ENDPOINTS_.find(x=>x.path===PATH)};if(!info.path)throw Error('Unsupported Studio operation');delete info.successAction;delete info.failAction;delete info.requestAction;window[KEY]={pending:true};n.postApiaryData_(info,{},'data',BODY).then(r=>{window[KEY]={done:true,result:r.data||r}},e=>{window[KEY]={done:true,error:String(e)}});return 'started'})()"""
  js=js.replace('PATH',json.dumps(path)).replace('KEY',json.dumps(key)).replace('BODY',json.dumps(body))
  self.evaluate(js)
  for _ in range(45):
   value=json.loads(self.evaluate('JSON.stringify(window['+json.dumps(key)+']||{pending:true})'))
   if value.get('done'):
    self.evaluate('delete window['+json.dumps(key)+'];true')
    result=value.get('result',{})
    if value.get('error') or result.get('errors') or result.get('error') or result.get('response',{}).get('error'):raise RuntimeError('YouTube rejected '+path+': '+str(value.get('error') or result.get('errors') or result.get('error') or result.get('response',{}).get('error'))[:400])
    return result
   time.sleep(1)
  raise TimeoutError('YouTube Studio request timed out: '+path)
 def status(self,ids):
  result=self.post('/live/get_broadcast_status',dict(videoIds=ids,includeLive=True))
  return {r['videoId']:r for r in result.get('broadcastStatus',[])}
 def create(self,entry,config):
  body=dict(useMasks=True,broadcastSource='BROADCAST_SOURCE_ENCODER',broadcastType='BROADCAST_SCHEDULED',videoMetadata=dict(title=entry['title'],description=config['description']+'\n\nSession: '+entry['key']+' to '+datetime.fromtimestamp(entry['end'],ZONE).isoformat()+'. Saved six-hour observation replay.',videoCategory='CATEGORY_PEOPLE',privacyStatus='PUBLIC'),videoMetadataMask=dict(setTitle=True,setDescription=True,setVideoCategory=True,setPrivacyStatus=True),broadcastMetadata=dict(enableMonitorStream=False,scheduleMetadata=dict(scheduledStartTimeSec=int(entry['start'])),latencyMode='LATENCY_NORMAL'),broadcastMetadataMask=dict(setEnableMonitorStream=True,scheduleMetadataMask=dict(setScheduledStartTimeSec=True),setLatencyMode=True),targetEntity=dict(externalChannelId=config['channel']))
  result=self.post('/live/create_broadcast',body)
  video=result.get('videoId')
  if not video:
   for command in result.get('commands',[]):
    video=command.get('setBroadcastInfoCommand',{}).get('videoId')
    if video:break
  if not video:raise RuntimeError('Created broadcast returned no identifier; reconcile before retrying')
  return video
 def configure(self,video):
  self.post('/video_manager/metadata_update',dict(encryptedVideoId=video,videoReadMask={},madeForKids=dict(operation='MDE_MADE_FOR_KIDS_UPDATE_OPERATION_SET',newMfk='MDE_MADE_FOR_KIDS_TYPE_NOT_MFK')))
 def bind(self,video):self.post('/live/bind_broadcast',dict(videoId=video,downgradeLatencyToBind=True))
 def start(self,video):self.post('/live/start_broadcast',dict(videoId=video))
 def complete(self,video):self.post('/live/stop_broadcast',dict(videoId=video))

def cycle(config,root,api,epoch=None):
 now=time.time() if epoch is None else epoch;state=json.loads((root/'sessions.json').read_text()) if (root/'sessions.json').exists() else dict(sessions={})
 entries=state['sessions'];current=slot(now);upcoming=slot(current['end']+1)
 def persist():save(root/'sessions.json',state)
 def ensure(window):
  entry=entries.setdefault(window['key'],dict(window))
  if not entry.get('video_id'):
   if entry.get('creation_pending'):raise RuntimeError('Broadcast creation outcome uncertain; reconciliation required for '+entry['key'])
   entry['creation_pending']=True;persist()
   video=api.create(entry,config);entry.update(video_id=video,watch_url='https://www.youtube.com/watch?v='+video,creation_pending=False);persist()
  if not entry.get('configured'):
   api.configure(entry['video_id']);entry['configured']=True;persist()
  return entry
 target=ensure(current);ensure(upcoming)
 active=state.get('active_video_id');wanted=target['video_id']
 # No polling is needed between boundaries once the current session is confirmed live.
 if active==wanted and target.get('state')=='live':
  if now-state.get('last_api_check',0)>=300:
   confirmed=api.status([wanted]).get(wanted,{})
   if confirmed.get('lifeCycleStatus')!='LIFE_CYCLE_LIVE':raise RuntimeError('Current session is no longer confirmed live; check YouTube Studio')
   state['last_api_check']=now;persist()
  save(root/'session-status.json',dict(state='live',watch_url=target['watch_url'],next_boundary=target['end'],timezone=str(ZONE),updated_epoch=now));return state
 ids=list(dict.fromkeys(x for x in (active,wanted) if x));statuses=api.status(ids);new=statuses.get(wanted,{})
 if wanted not in statuses:raise RuntimeError('Scheduled broadcast status unavailable; leaving current session unchanged')
 if active and active!=wanted:
  old=statuses.get(active)
  if old is None:raise RuntimeError('Current broadcast status unavailable; retry before ending it')
  lifecycle=old.get('lifeCycleStatus')
  if lifecycle in ('LIFE_CYCLE_LIVE','LIFE_CYCLE_TESTING'):
   # Verify the incoming encoder before closing a live archive.
   if new.get('ingestionStatus')!='INGESTION_STATUS_ACTIVE':
    api.bind(wanted);save(root/'session-status.json',dict(state='waiting_for_encoder',updated_epoch=now));return state
   api.complete(active)
   for entry in entries.values():
    if entry.get('video_id')==active:entry.update(state='completing',ended_epoch=now)
   persist();return state
  if lifecycle not in ('LIFE_CYCLE_COMPLETE','LIFE_CYCLE_REVOKED'):return state
  for entry in entries.values():
   if entry.get('video_id')==active:entry.update(state='complete',youtube_confirmed_complete_epoch=now)
  state['active_video_id']=None;persist()
 if new.get('lifeCycleStatus')=='LIFE_CYCLE_LIVE':
  state['active_video_id']=wanted;target.update(state='live',confirmed_live_epoch=now);persist()
 elif new.get('lifeCycleStatus') in ('LIFE_CYCLE_CREATED','LIFE_CYCLE_READY'):
  api.bind(wanted)
  if new.get('ingestionStatus')=='INGESTION_STATUS_ACTIVE':api.start(wanted)
 elif new.get('lifeCycleStatus')=='LIFE_CYCLE_TESTING':api.start(wanted)
 else:raise RuntimeError('Scheduled session cannot start: '+str(new.get('lifeCycleStatus')))
 save(root/'session-status.json',dict(state='transitioning' if state.get('active_video_id')!=wanted else 'live',watch_url=target['watch_url'],next_boundary=target['end'],timezone=str(ZONE),updated_epoch=now))
 return state

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();config=json.loads(a.config.read_text());root=a.config.parent
 if not config.get('enabled'):return
 with (root/'sessions.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  try:cycle(config,root,Studio())
  except Exception as exc:save(root/'session-status.json',dict(state='retry_pending',error=str(exc),updated_epoch=time.time()));raise
if __name__=='__main__':main()
