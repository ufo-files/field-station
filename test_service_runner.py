import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class ShutdownTests(unittest.TestCase):
    def check_shutdown(self, ignore):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'service.lock'
            ready = Path(directory) / 'ready'
            code = ("import fcntl,signal,time,pathlib; "
                    f"f=open({str(lock)!r},'w'); fcntl.flock(f,fcntl.LOCK_EX); "
                    + ("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if ignore else "")
                    + f"pathlib.Path({str(ready)!r}).touch(); time.sleep(60)")
            runner = subprocess.Popen([sys.executable, '-c',
                'from service_runner import supervise; import sys; '
                f'sys.exit(supervise({[sys.executable, "-c", code]!r}, grace=.3))'])
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(ready.exists())
                runner.send_signal(signal.SIGTERM)
                runner.wait(timeout=3)
                with lock.open('a') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if runner.poll() is None:
                    runner.kill()
                    runner.wait()

    def test_graceful_shutdown_releases_lock(self):
        self.check_shutdown(False)

    def test_unresponsive_child_releases_lock(self):
        self.check_shutdown(True)


if __name__ == '__main__':
    unittest.main()

class StorageTests(unittest.TestCase):
    def test_fast_storage_identity_is_required_for_review_service(self):
        from unittest.mock import patch
        from service_runner import storage_ready
        env = dict(CAPTURE_VOLUME='/Volumes/Field', CAPTURE_VOLUME_ID='field',
                   FAST_STORAGE_VOLUME='/Volumes/Fast', FAST_STORAGE_VOLUME_ID='fast')
        with patch.object(Path, 'is_mount', return_value=True), patch.object(Path, 'read_text', side_effect=['field', 'wrong']*2):
            self.assertFalse(storage_ready(env, 'lab'))
            self.assertFalse(storage_ready(env, 'recognition'))
        with patch.object(Path, 'is_mount', return_value=True), patch.object(Path, 'read_text', side_effect=['field', 'fast']*2):
            self.assertTrue(storage_ready(env, 'lab'))
            self.assertTrue(storage_ready(env, 'recognition'))
        with patch.object(Path, 'is_mount', return_value=False):
            self.assertFalse(storage_ready(env, 'lab'))
            self.assertFalse(storage_ready(env, 'recognition'))
