import tempfile,threading,time,json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from provisional_capture import ProvisionalCapture

class ProvisionalTests(TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.starts=[]
  self.station=SimpleNamespace(lock=threading.RLock(),active=None,motion_trigger=SimpleNamespace(last_motion_epoch=None),experiments=SimpleNamespace(pause_exports=lambda:True,resume_exports=lambda:None),data_path=lambda sid:self.root/sid)
  def start(body,motion_event):
   self.starts.append(motion_event);folder=self.root/'20261029T200000Z-abcdef';folder.mkdir(exist_ok=True);self.station.active=dict(id=folder.name,state='recording',started_epoch=time.time()-10,capture_origin='motion_trigger')
  self.station.start=start;self.handler=ProvisionalCapture(self.station)
 def tearDown(self):self.tmp.cleanup()
 def body(self):return dict(frame_epoch=time.time()-.5,sequence=100,generation='run-abcdef',boxes=[[400,200,12,8]],model_id='a'*32)
 def test_capture_is_provisional_durable_idempotent(self):
  body=self.body();a=self.handler.receive(body);self.handler.receive(body)
  self.assertEqual(len(self.starts),1);self.assertEqual(self.station.active['capture_origin'],'provisional_motion')
  job=json.loads((self.root/a['session_id']/'provisional.json').read_text());self.assertEqual(job['classification'],'unclassified');self.assertFalse(job['automatic_deletion'])
  self.assertEqual(len((self.root/a['session_id']/'provisional-candidates.jsonl').read_text().splitlines()),1)
  self.assertEqual(self.starts[0]['motion_started_epoch'],body['frame_epoch'])
 def test_bad_or_stale_requests_do_not_start(self):
  for extra in ({'frame_epoch':time.time()-16},{'sequence':-1},{'generation':'../x'},{'boxes':[]},{'boxes':[[1919,0,10,10]]},{'onset_epoch':time.time()-10}):
   with self.assertRaises(ValueError):self.handler.receive(dict(self.body(),**extra))
  self.assertEqual(self.starts,[])
 def test_manual_session_is_not_reclassified(self):
  self.station.start({},{});self.station.active['capture_origin']='manual'
  self.handler.receive(self.body());self.assertEqual(self.station.active['capture_origin'],'manual');self.assertNotIn('provisional',self.station.active)
 def test_authenticated_http_route_calls_provisional_capture(self):
  import io,server
  from unittest.mock import patch
  body=json.dumps(self.body()).encode();handler=object.__new__(server.Handler);handler.path='/api/provisional/detection';handler.headers={'X-Station-Token':server.TOKEN,'Content-Length':str(len(body))};handler.rfile=io.BytesIO(body);responses=[];handler.send=lambda code,data:responses.append((code,data))
  with patch.object(server,'STATION',self.station,create=True):handler.do_POST()
  self.assertEqual(responses[0][0],200);self.assertEqual(len(self.starts),1)
 def test_manual_takeover_keeps_existing_clip(self):
  response=self.handler.receive(self.body());sid=response['session_id'];self.station.active['capture_mode']='motion_window'
  self.handler.manual({'session_id':sid});self.assertEqual(len(self.starts),1);self.assertEqual(self.station.active['capture_origin'],'manual');self.assertNotIn('capture_mode',self.station.active)
