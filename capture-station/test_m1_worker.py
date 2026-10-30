import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from m1_worker import encode
from m1_encode import ssh_args

class WorkerTests(unittest.TestCase):
    def test_ssh_is_key_only_and_checks_host_identity(self):
        args=ssh_args(dict(host='100.113.237.2',username='worker'))
        self.assertIn('BatchMode=yes',args)
        self.assertIn('StrictHostKeyChecking=yes',args)
        with self.assertRaises(ValueError):ssh_args(dict(host='-oProxyCommand=bad',username='worker'))

    def test_truncated_transfer_never_encodes_and_removes_scratch(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('m1_worker.shutil.disk_usage',return_value=SimpleNamespace(free=100*1024**3)),patch('m1_worker.sys.stdin',SimpleNamespace(buffer=io.BytesIO(b'123'))),patch('m1_worker.subprocess.run') as run:
                with self.assertRaisesRegex(OSError,'Incomplete'):encode(10,'unused',root)
                run.assert_not_called()
            self.assertEqual(list(Path(root).glob('job-*')),[])

    def test_wrong_checksum_never_encodes_and_removes_scratch(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('m1_worker.shutil.disk_usage',return_value=SimpleNamespace(free=100*1024**3)),patch('m1_worker.sys.stdin',SimpleNamespace(buffer=io.BytesIO(b'123'))),patch('m1_worker.subprocess.run') as run:
                with self.assertRaisesRegex(OSError,'checksum'):encode(3,'wrong',root)
                run.assert_not_called()
            self.assertEqual(list(Path(root).glob('job-*')),[])


class LiveTests(unittest.TestCase):
    def test_live_encoder_uses_hardware_and_rejects_unencrypted_ingest(self):
        from m1_live import live_args
        config=dict(publish_url='rtmps://a.rtmps.youtube.com/live2/test-key',source='http://100.117.92.45:8090/preview.mjpeg?fps=30')
        args=live_args(config)
        self.assertIn('h264_videotoolbox',args)
        self.assertIn('600',args)
        config['publish_url']='rtmp://a.rtmp.youtube.com/live2/test-key'
        with self.assertRaises(ValueError):live_args(config)

    def test_preparation_is_unlisted_and_reuses_durable_ids(self):
        from unittest.mock import Mock
        from youtube_live import prepare
        api=Mock();state={}
        stream=dict(id='stream-id',cdn=dict(ingestionInfo=dict(rtmpsIngestionAddress='rtmps://a.rtmps.youtube.com/live2',streamName='secret')))
        with patch('youtube_live.private_save'),patch('youtube_live.post',side_effect=[stream,dict(id='broadcast-id'),{}]) as post:
            prepare(api,state)
            self.assertIn('snippet',post.call_args_list[0].kwargs['part'])
            self.assertIn('contentDetails',post.call_args_list[0].kwargs['part'])
            broadcast=post.call_args_list[1].args[2]
            self.assertEqual(broadcast['status']['privacyStatus'],'unlisted')
            self.assertTrue(broadcast['contentDetails']['enableAutoStart'])
        with patch('youtube_live.private_save'),patch('youtube_live.post',return_value={}) as post:
            prepare(api,state)
            self.assertEqual(post.call_count,1)
            self.assertEqual(post.call_args.args[1],'liveBroadcasts/bind')
