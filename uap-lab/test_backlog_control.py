import fcntl,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from backlog_control import stop_orphaned_service

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
