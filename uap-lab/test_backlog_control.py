import fcntl,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from backlog_control import stop_orphaned_service
from backlog_reset import capture_health

class EmptyCaptureTests(unittest.TestCase):
 def test_closed_radio_only_generation_has_no_video_frames(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   for name in ('generation.json','closed.json','rf-000001.jsonl'):(root/name).write_text('{}')
   self.assertEqual(capture_health(root)['captured_frames'],0)
 def test_missing_health_with_video_evidence_still_fails(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   for name in ('generation.json','closed.json','segments-index.jsonl'):(root/name).write_text('{}')
   with self.assertRaises(FileNotFoundError):capture_health(root)

class OrphanShutdownTests(unittest.TestCase):
 def test_unresponsive_orphan_releases_existing_lock(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'worker.py';lock=Path(d)/'service.lock';ready=Path(d)/'ready'
   p.write_text('import fcntl,signal,time\nfrom pathlib import Path\nf=open('+repr(str(lock))+',"w");fcntl.flock(f,fcntl.LOCK_EX)\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nPath('+repr(str(ready))+').touch()\ntime.sleep(60)\n')
   child=subprocess.Popen([sys.executable,str(p)],start_new_session=True)
   try:
    for _ in range(100):
     if ready.exists():break
     time.sleep(.03)
    assert ready.exists()
    start=time.monotonic();stop_orphaned_service(p,grace=.2);child.wait(timeout=2)
    with lock.open('a') as f:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert lock.exists()
    print('PASS: unresponsive orphan stopped and lock released in',round(time.monotonic()-start,2),'seconds; lock file preserved')
   finally:
    if child.poll() is None:child.kill();child.wait()

if __name__=="__main__":unittest.main()

class RequestPublicationTests(unittest.TestCase):
 def test_new_request_is_visible_before_child_starts(self):
  import backlog_control as control
  from unittest.mock import patch,Mock
  with tempfile.TemporaryDirectory() as directory,patch.object(control,'RUN',Path(directory)):
   control.save(control.RUN/'latest.json',dict(phase='complete',request_id='old',review={'frames_cleared':0}))
   def spawn(*args,**kwargs):
    state=control.status()
    self.assertEqual(state['phase'],'queued');self.assertTrue(state['busy']);self.assertNotEqual(state['request_id'],'old')
    return Mock(pid=123)
   with patch.object(control.subprocess,'Popen',side_effect=spawn):result=control.start()
   self.assertEqual(result['pid'],123);self.assertEqual(control.status()['request_id'],result['request_id'])
 def test_spawn_failure_is_not_left_busy(self):
  import backlog_control as control
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as directory,patch.object(control,'RUN',Path(directory)):
   with patch.object(control.subprocess,'Popen',side_effect=OSError('spawn failed')):
    with self.assertRaises(OSError):control.start()
   self.assertEqual(control.status()['phase'],'error');self.assertFalse(control.status()['busy'])
 def test_abandoned_queued_request_reports_failure(self):
  import backlog_control as control
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as directory,patch.object(control,'RUN',Path(directory)):
   control.save(control.RUN/'latest.json',dict(phase='queued',request_id='new',busy=True,queued_epoch=time.time()-60))
   self.assertEqual(control.status()['phase'],'error')
