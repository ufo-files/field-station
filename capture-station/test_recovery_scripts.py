import os
from pathlib import Path
import subprocess
import tempfile
import unittest

class RecoveryScriptTests(unittest.TestCase):
    def run_helper(self,uuid):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            scripts={
                'mountpoint':'exit 0',
                'findmnt':'printf "%s\\n" "$FAKE_UUID"',
                'cat':'printf "S6XBNS0W321351N\\n"',
                'date':'printf "1000\\n"',
                'stat':'printf "1000\\n"',
                'systemctl':'printf "%s\\n" "$*" >> "$CALLS"\ncase "$1" in is-active) exit 1;; esac',
            }
            for name,body in scripts.items():
                path=root/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o755)
            env=dict(os.environ,PATH=str(root)+':'+os.environ['PATH'],FAKE_UUID=uuid,CALLS=str(root/'calls'))
            subprocess.run(['/bin/sh',str(Path(__file__).with_name('recover-station.sh'))],env=env,check=True)
            return (root/'calls').read_text() if (root/'calls').exists() else ''
    def test_wrong_ssd_does_not_start_writers(self):
        self.assertEqual(self.run_helper('wrong-uuid'),'')
    def test_correct_ssd_restarts_missing_services(self):
        calls=self.run_helper('a8ec8f1e-b658-4182-87b4-34b56cf70a5b')
        for name in ('openwebrx.service','hackrf-signal-logger.service','hackrf-signal-publish.timer','smbd.service'):
            self.assertIn('start '+name+'\n',calls)
