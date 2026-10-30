import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab/recognition'))
from recognition_alerts import AlertOutbox,render_screenshot
from mail_alerts import deliver,compose
class AlertTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=dict(sender='contact@example.org',recipient='owner@example.org');self.calls=[]
 def tearDown(self):self.tmp.cleanup()
 def queued(self,key='a',epoch=100,schema=2):
  folder=self.root/key;folder.mkdir(exist_ok=True);Image.new('RGB',(1600,900)).save(folder/'object.png')
  event=dict(schema=schema,id=key,detected_epoch=epoch,created_epoch=epoch,generation='run',sequence=1,pts_seconds=.1,track='object',model='model',score=.99,bounds=[1,2,8,9],screenshot='object.png',screenshot_description='Scene and zoom')
  (folder/'event.json').write_text(json.dumps(event));return folder
 def send(self,folder,now=100,**kw):return deliver(folder,self.config,send=lambda *args:self.calls.append(args),check=lambda _:None,now=now,**kw)
 def test_1300_candidates_send_only_one(self):
  for i in range(1300):self.send(self.queued(str(i)))
  self.assertEqual(len(self.calls),1)
 def test_rate_limit_survives_restart_and_old_queue_is_not_deferred(self):
  self.send(self.queued('a'));folder=self.queued('b');self.assertEqual(self.send(folder,101)['state'],'suppressed')
  self.assertEqual(self.send(folder,2000)['state'],'suppressed');self.assertEqual(len(self.calls),1)
 def test_four_email_rolling_daily_cap(self):
  for i in range(5):self.send(self.queued(str(i),epoch=100+1801*i),now=100+1801*i)
  self.assertEqual(len(self.calls),4)
 def test_legacy_cancelled_uncertain_and_stale_never_send(self):
  for state in ['cancelled','submitting','uncertain','suppressed']:
   f=self.queued(state);(f/'delivery.json').write_text(json.dumps(dict(state=state)));self.send(f)
  self.send(self.queued('legacy',schema=1));self.send(self.queued('stale',epoch=0),now=400);self.assertEqual(self.calls,[])
 def test_send_once_with_exactly_one_large_image(self):
  f=self.queued();self.send(f);self.send(f);self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][2],f/'object.png');self.assertIn('Human confirmation: no',self.calls[0][1])
 def test_timeout_never_retries_or_releases_budget(self):
  f=self.queued()
  def fail(*args):raise TimeoutError('uncertain')
  self.assertEqual(deliver(f,self.config,send=fail,check=lambda _:None,now=100)['state'],'uncertain')
  self.send(f);self.send(self.queued('b'),now=101);self.assertEqual(self.calls,[])
 def test_changing_ids_group_into_one_sustained_event(self):
  out=AlertOutbox(self.root);frame=np.zeros((1080,1920),dtype=np.uint8)
  with patch('recognition_alerts.time.time',return_value=10000):
   for i in range(1300):
    obs=dict(proposed_track_id=str(i),model='model',scores={'anomalous':.99},suggested_label='anomalous',box=[100,100,11,9])
    out.submit('run',dict(sequence=i,pts_seconds=i/60,received_epoch=10000,observations=[obs],alert_frame=frame),[0],[b'crop'])
   self.assertEqual(len(list(self.root.glob('*/event.json'))),1);self.assertFalse(AlertOutbox(self.root).wants_frame())
  f=next(self.root.glob('*/event.json'));e=json.loads(f.read_text());self.assertGreaterEqual(e['persistence_seconds'],2);self.assertGreaterEqual(e['grouped_observations'],10)
  with Image.open(f.parent/'object.png') as im:self.assertEqual(im.size,(1600,900))
 def test_one_frame_unknown_and_old_backlog_do_not_notify(self):
  out=AlertOutbox(self.root,not_before=101)
  row=dict(sequence=1,pts_seconds=1,received_epoch=100,observations=[dict(suggested_label='anomalous')])
  self.assertEqual(out.submit('run',row,[0],[b'crop']),0)
  row.update(received_epoch=200,observations=[dict(suggested_label='unknown')]);self.assertEqual(out.submit('run',row,[0],[b'crop']),0)
  self.assertFalse(list(self.root.glob('*/event.json')))
 def test_render_has_context_and_preserves_native_zoom_pixels(self):
  frame=np.zeros((1080,1920),dtype=np.uint8);frame[100:109,100:111]=255;p=self.root/'screenshot.png';render_screenshot(frame,[100,100,11,9],p)
  with Image.open(p) as im:
   self.assertEqual(im.size,(1600,900));self.assertEqual(im.getpixel((1370,300)),(255,255,255))
if __name__=='__main__':unittest.main()
