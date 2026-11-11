import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from youtube_sessions import cycle,slot,ZONE
class API:
 def __init__(self,states):self.states=states;self.calls=[]
 def status(self,ids):return {i:self.states[i] for i in ids if i in self.states}
 def create(self,e,c):self.calls.append(('create',e['key']));return 'new'
 def configure(self,v):self.calls.append(('configure',v))
 def bind(self,v):self.calls.append(('bind',v))
 def start(self,v):self.calls.append(('start',v))
 def complete(self,v):self.calls.append(('complete',v))
class SessionTests(unittest.TestCase):
 def test_four_wall_clock_slots_and_dst(self):
  for hour in range(24):
   s=slot(datetime(2026,11,11,hour,tzinfo=ZONE).timestamp());self.assertEqual(datetime.fromtimestamp(s['start'],ZONE).hour,(hour//6)*6)
  s=slot(datetime(2026,11,1,0,tzinfo=ZONE).timestamp());self.assertEqual(s['end']-s['start'],7*3600)
 def state(self,p,now):
  a=slot(now);b=slot(a['end']+1);old=slot(a['start']-1)
  state=dict(active_video_id='old',sessions={a['key']:dict(a,video_id='next',watch_url='next-url',configured=True),b['key']:dict(b,video_id='future',configured=True),old['key']:dict(old,video_id='old',watch_url='old-url',configured=True,state='live')});(p/'sessions.json').write_text(json.dumps(state));return state
 def test_complete_then_start_and_preserve_replay(self):
  now=datetime(2026,11,11,12,tzinfo=ZONE).timestamp()
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);self.state(root,now);api=API({'old':dict(lifeCycleStatus='LIFE_CYCLE_LIVE'),'next':dict(lifeCycleStatus='LIFE_CYCLE_TESTING',ingestionStatus='INGESTION_STATUS_ACTIVE')})
   cycle({},root,api,now);self.assertEqual(api.calls,[('complete','old')])
   api.states['old']['lifeCycleStatus']='LIFE_CYCLE_COMPLETE';cycle({},root,api,now+15);self.assertEqual(api.calls[-1],('start','next'))
   api.states['next']['lifeCycleStatus']='LIFE_CYCLE_LIVE';state=cycle({},root,api,now+30);self.assertEqual(state['active_video_id'],'next');self.assertTrue(any(e.get('watch_url')=='old-url' and e.get('state')=='complete' for e in state['sessions'].values()))
 def test_no_encoder_or_missing_status_does_not_end_live_session(self):
  now=datetime(2026,11,11,12,tzinfo=ZONE).timestamp()
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);self.state(root,now);api=API({'old':dict(lifeCycleStatus='LIFE_CYCLE_LIVE'),'next':dict(lifeCycleStatus='LIFE_CYCLE_READY',ingestionStatus='INGESTION_STATUS_INACTIVE')});cycle({},root,api,now);self.assertNotIn(('complete','old'),api.calls)
   api.states.pop('old')
   with self.assertRaises(RuntimeError):cycle({},root,api,now)
 def test_restart_does_not_duplicate_existing_sessions(self):
  now=datetime(2026,11,11,12,tzinfo=ZONE).timestamp()
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);s=self.state(root,now);s['active_video_id']='next';s['last_api_check']=now;s['sessions'][slot(now)['key']]['state']='live';(root/'sessions.json').write_text(json.dumps(s));api=API({});cycle({},root,api,now);self.assertEqual(api.calls,[])
