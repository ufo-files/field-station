import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab/recognition'))
from recognition_alerts import AlertOutbox,render_screenshot
from mail_alerts import deliver,compose,send_requested_update
class AlertTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=dict(sender='contact@example.org',recipient='owner@example.org',review_base_url='http://station.test:8091');self.calls=[]
 def tearDown(self):self.tmp.cleanup()
 def queued(self,key='a',epoch=100,schema=3):
  folder=self.root/key;folder.mkdir(exist_ok=True);Image.new('RGB',(1920,1080)).save(folder/'object.png');Image.new('RGB',(1024,512)).save(folder/'object-detail.png')
  event=dict(schema=schema,id=key,detected_epoch=epoch,created_epoch=epoch,generation='run',sequence=1,pts_seconds=.1,track='object',model='model',score=.99,bounds=[1,2,8,9],screenshots=['object.png','object-detail.png'],screenshot_description='Scene and zoom')
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
  f=self.queued();self.send(f);self.send(f);self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][2],[f/'object.png',f/'object-detail.png']);self.assertIn('Human confirmation: no',self.calls[0][1])
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
  with Image.open(f.parent/'object.png') as im:self.assertEqual(im.size,(1920,1080))
 def test_one_frame_unknown_and_old_backlog_do_not_notify(self):
  out=AlertOutbox(self.root,not_before=101)
  row=dict(sequence=1,pts_seconds=1,received_epoch=100,observations=[dict(suggested_label='anomalous')])
  self.assertEqual(out.submit('run',row,[0],[b'crop']),0)
  row.update(received_epoch=200,observations=[dict(suggested_label='unknown')]);self.assertEqual(out.submit('run',row,[0],[b'crop']),0)
  self.assertFalse(list(self.root.glob('*/event.json')))
 def test_render_has_context_and_preserves_native_zoom_pixels(self):
  frame=np.zeros((1080,1920),dtype=np.uint8);frame[100:109,100:111]=255;p=self.root/'screenshot.png';render_screenshot(frame,[100,100,11,9],p)
  with Image.open(p) as im:
   self.assertEqual(im.size,(1920,1080));self.assertEqual(im.getpixel((500,500)),(0,0,0))
  with Image.open(self.root/'object-detail.png') as im:self.assertEqual(max(im.size),1024);self.assertGreater(np.asarray(im).max(),0)
  with Image.open(self.root/'native-object.png') as im:self.assertEqual(im.size,(64,64))
 def test_crop_matches_the_entire_visible_box(self):
  frame=np.zeros((1080,1920),dtype=np.uint8);frame[100:106,100:108]=200;frame[100:106,120:128]=255
  box=render_screenshot(frame,[100,100,8,6],self.root/'original.png');x,y,w,h=box
  with Image.open(self.root/'native-object.png') as im:np.testing.assert_array_equal(np.asarray(im)[:,:,0],frame[y:y+h,x:x+w]);self.assertTrue(200 in np.asarray(im));self.assertTrue(255 in np.asarray(im))
 def test_detail_is_smoothed_and_original_frame_stays_uncropped(self):
  frame=np.zeros((1080,1920),dtype=np.uint8);frame[101:105,102:106]=255
  render_screenshot(frame,[100,100,11,9],self.root/'original.png')
  with Image.open(self.root/'object-detail.png') as im:self.assertGreater(len(np.unique(np.asarray(im.convert('L')))),20)
  with Image.open(self.root/'original.png') as im:
   self.assertEqual(im.size,(1920,1080));self.assertEqual(im.getpixel((0,0)),(0,0,0));self.assertEqual(im.getpixel((1919,1079)),(0,0,0))
   yellow=np.all(np.asarray(im)==[255,220,0],axis=2);ys,xs=np.where(yellow);self.assertGreaterEqual(xs.max()-xs.min(),59);self.assertGreaterEqual(ys.max()-ys.min(),59)
 def test_requested_email_has_review_link_in_actual_mail_arguments(self):
  key='a'*32;folder=self.queued(key);config=dict(self.config,outbox=str(self.root),requested_update_event=key)
  from types import SimpleNamespace
  with patch('mail_alerts.preflight'),patch('mail_alerts.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='accepted_by_mail')) as call:
   send_requested_update(config)
   args=call.call_args.args[0];url='http://station.test:8091/email-review?id='+key
   self.assertEqual(args[-1],url);self.assertIn(url,Path(args[5]).read_text());self.assertEqual(len(args),9)
   send_requested_update(config);self.assertEqual(call.call_count,1)
 def test_no_link_blocks_requested_send(self):
  key='a'*32;folder=self.queued(key);config=dict(self.config,outbox=str(self.root),requested_update_event=key);config.pop('review_base_url')
  with patch('mail_alerts.preflight'),patch('mail_alerts.subprocess.run') as call:
   with self.assertRaises(ValueError):send_requested_update(config)
   call.assert_not_called()
if __name__=='__main__':unittest.main()
