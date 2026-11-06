import os,tempfile,unittest,threading,time
from pathlib import Path
os.environ.setdefault('UAP_LAB_DATA',tempfile.mkdtemp(prefix='uap-live-test-'))
import cv2,numpy as np
import lab
from unittest.mock import Mock
from live_matcher import LiveMatcher
from live_monitor import LiveMonitor

class LiveMatcherTests(unittest.TestCase):
    def target(self):
        im=np.zeros((40,40),np.uint8);cv2.circle(im,(20,20),12,220,-1);cv2.rectangle(im,(13,15),(22,24),80,-1);return im
    def test_coarse_proposals_are_verified_at_native_pixels(self):
        target=self.target();image=np.zeros((800,1000,3),np.uint8)
        image[100:140,200:240]=cv2.cvtColor(target,cv2.COLOR_GRAY2BGR);image[500:540,700:740]=cv2.cvtColor(target,cv2.COLOR_GRAY2BGR)
        matcher=LiveMatcher([('anomalous',target)],budget=.01)
        found,stats=matcher.predict(image,.97,['anomalous']);self.assertEqual(sorted(m['box'] for m in found),[[200,100,40,40],[700,500,40,40]]);self.assertEqual(stats['template_count'],1)
        self.assertTrue(all(m['score']>=.97 for m in found))
    def test_budget_rotates_over_entire_bank(self):
        templates=[('anomalous',np.random.default_rng(i).integers(0,255,(20,20),dtype=np.uint8)) for i in range(20)];matcher=LiveMatcher(templates,budget=0)
        image=np.zeros((100,100,3),np.uint8)
        for expected in (8,16,4):matcher.predict(image,.97,['anomalous']);self.assertEqual(matcher.cursor,expected)

class ManualSessionTests(unittest.TestCase):
    def monitor(self,path):
        monitor=LiveMonitor.__new__(LiveMonitor);monitor.folder=path;monitor.lock=threading.RLock();monitor.next_capture_attempt=0;monitor.state=dict(camera_no_signal=False,frame_epoch=time.time(),preview_error=None);return monitor
    def test_no_signal_stale_error_and_unknown_block_before_station_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor=self.monitor(Path(tmp));monitor.station=Mock()
            for state in ({},dict(camera_no_signal=True,frame_epoch=time.time()),dict(camera_no_signal=False,frame_epoch=time.time()-10),dict(camera_no_signal=False,frame_epoch=time.time(),preview_error='unavailable'),dict(camera_no_signal=False,frame_epoch=time.time()+10)):
                monitor.state=state
                with self.subTest(state=state),self.assertRaisesRegex(ValueError,'without a live camera signal'):monitor.manual_start({})
            monitor.station.assert_not_called()
    def test_stop_remains_available_after_signal_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor=self.monitor(Path(tmp));monitor.state=dict(camera_no_signal=True)
            monitor.station=Mock(side_effect=[dict(active=dict(id='existing')),dict(state='completed')])
            self.assertEqual(monitor.manual_stop(dict(session_id='existing'))['state'],'stopped')
            self.assertEqual(monitor.station.call_args.args,('/api/stop',dict(expected_session_id='existing')))
    def test_manual_controls_preserve_model_trigger_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor=self.monitor(Path(tmp));calls=[];active=None
            def station(path,body=None):
                nonlocal active
                calls.append((path,body))
                if path=='/api/session':return dict(csrf='test',active=active,triggers=dict(motion=False,rf=False,scheduled=False))
                if path=='/api/start':active=dict(id='20261029T030000Z-abcdef');return active
                if path=='/api/stop':active=None;return dict(state='completed')
                raise AssertionError(path)
            monitor.station=station
            started=monitor.manual_start({});self.assertEqual(started['state'],'recording')
            self.assertEqual(monitor.session_status()['recent_manual'][0]['kind'],'manual')
            with self.assertRaisesRegex(ValueError,'changed'):monitor.manual_stop(dict(session_id='wrong'))
            monitor.manual_stop(dict(session_id=started['session_id']));self.assertIsNone(active)
            self.assertEqual([p for p,b in calls if p not in ('/api/session','/api/start','/api/stop')],[])
if __name__=='__main__':unittest.main()

class PreviewIsolationTests(unittest.TestCase):
    def test_preview_keeps_updating_without_an_inference_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'preview.jpg';cv2.imwrite(str(path),np.zeros((96,128,3),np.uint8))
            monitor=LiveMonitor(preview_path=path,start_workers=False);monitor.state['phase']='analyzing'
            thread=threading.Thread(target=monitor.preview_work);thread.start()
            try:
                for _ in range(50):
                    if monitor.image:break
                    time.sleep(.02)
                self.assertIsNotNone(monitor.image);before=monitor.image
                cv2.imwrite(str(path),np.full((96,128,3),200,np.uint8))
                for _ in range(75):
                    if monitor.image!=before:break
                    time.sleep(.02)
                self.assertNotEqual(monitor.image,before);self.assertEqual(monitor.state['phase'],'analyzing');self.assertLess(time.time()-monitor.state['frame_epoch'],2)
            finally:monitor.stop_event.set();thread.join(timeout=3)

class BatchMatcherTests(unittest.TestCase):
    def test_complete_bank_preserves_multiple_targets_and_deduplicates_workers(self):
        from batch_matcher import BatchMatcher
        target=LiveMatcherTests().target();image=np.zeros((800,1000,3),np.uint8)
        image[100:140,200:240]=cv2.cvtColor(target,cv2.COLOR_GRAY2BGR);image[500:540,700:740]=cv2.cvtColor(target,cv2.COLOR_GRAY2BGR)
        matcher=BatchMatcher([('anomalous',target)]*4)
        try:
            found=matcher.predict(image,.97,['anomalous']);self.assertEqual(sorted(v['box'] for v in found),[[200,100,40,40],[700,500,40,40]])
            self.assertTrue(all(v['detail_score']>=.55 for v in found))
        finally:matcher.close()
    def test_known_object_competes_across_workers_before_label_filter(self):
        from batch_matcher import BatchMatcher
        target=LiveMatcherTests().target();image=np.zeros((100,100,3),np.uint8);image[20:60,30:70]=cv2.cvtColor(target,cv2.COLOR_GRAY2BGR)
        matcher=BatchMatcher([('not_anomalous',target),('anomalous',target)])
        try:self.assertEqual(matcher.predict(image,.97,['anomalous']),[])
        finally:matcher.close()

class PreviewStorageIsolationTests(unittest.TestCase):
 def test_external_analysis_reads_do_not_block_preview(self):
  import os,threading,time
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'preview.jpg';cv2.imwrite(str(path),np.zeros((96,128,3),dtype=np.uint8))
   with patch.object(lab,'DATA',Path(tmp)),patch.dict(os.environ,{'UAP_NATIVE_EXTERNAL':'1'}):
    monitor=LiveMonitor(preview_path=path,start_workers=False)
    with patch.object(lab,'read',side_effect=AssertionError('Preview touched recording storage')):
     worker=threading.Thread(target=monitor.preview_work,daemon=True);worker.start()
     try:
      deadline=time.monotonic()+2
      while monitor.image is None and time.monotonic()<deadline:time.sleep(.01)
      self.assertIsNotNone(monitor.image)
      self.assertIsNone(monitor.state['preview_error'])
     finally:monitor.stop_event.set();worker.join(timeout=2)

class CameraCadenceTests(unittest.TestCase):
 def test_slow_analysis_never_replaces_fresh_camera_frames(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp,patch.object(lab,'DATA',Path(tmp)):
   path=Path(tmp)/'preview.jpg';cv2.imwrite(str(path),np.zeros((72,128,3),np.uint8))
   monitor=LiveMonitor(preview_path=path,start_workers=False)
   monitor.analysis_preview=(dict(source_received_epoch=time.time(),width=128,height=72,tags=[]),b'old-analysis-image')
   thread=threading.Thread(target=monitor.preview_work);thread.start()
   try:
    for _ in range(100):
     if monitor.image:break
     time.sleep(.005)
    self.assertEqual(monitor.image,path.read_bytes())
    self.assertEqual(monitor.state['preview_mode'],'camera')
    previous=monitor.state['frame_epoch'];temp=path.with_suffix('.tmp.jpg');cv2.imwrite(str(temp),np.full((72,128,3),200,np.uint8));temp.replace(path)
    deadline=time.monotonic()+.2
    while monitor.state['frame_epoch']==previous and time.monotonic()<deadline:time.sleep(.002)
    self.assertNotEqual(monitor.state['frame_epoch'],previous)
    self.assertEqual(monitor.image,path.read_bytes())
   finally:monitor.stop_event.set();thread.join(timeout=2)
