import io
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import server


class LivePreviewTests(unittest.TestCase):
    def handler(self, path):
        handler=object.__new__(server.Handler)
        handler.path=path
        handler.connection=Mock()
        handler.send=Mock()
        handler.send_response=Mock()
        handler.send_header=Mock()
        handler.end_headers=Mock()
        handler.wfile=io.BytesIO()
        return handler

    def test_invalid_rate_is_rejected(self):
        handler=self.handler('/preview.mjpeg?fps=1000')
        handler.live_preview()
        self.assertEqual(handler.send.call_args.args[0],400)

    def test_stale_camera_is_reported_before_stream_headers(self):
        handler=self.handler('/preview.mjpeg?fps=30')
        with patch.object(server,'STATION',SimpleNamespace(preview_age=lambda:6)):
            handler.live_preview()
        self.assertEqual(handler.send.call_args.args[0],503)
        handler.send_response.assert_not_called()

    def test_complete_frames_and_unchanged_frame_is_not_repeated(self):
        handler=self.handler('/preview.mjpeg?fps=60')
        stop=threading.Event()
        waits=[]
        with tempfile.TemporaryDirectory() as temporary:
            preview=Path(temporary)/'preview.jpg'
            first=b'\xff\xd8first-frame\xff\xd9'
            second=b'\xff\xd8second-frame\xff\xd9'
            preview.write_bytes(first)
            def wait(seconds):
                waits.append(seconds)
                if len(waits)==2:
                    preview.write_bytes(second)
                elif len(waits)==3:
                    stop.set()
            station=SimpleNamespace(preview_age=lambda:0,exiting=SimpleNamespace(is_set=stop.is_set,wait=wait))
            with patch.object(server,'STATION',station),patch.object(server,'PREVIEW',preview):
                handler.live_preview()
        body=handler.wfile.getvalue()
        self.assertEqual(body.count(b'--camera-frame\r\n'),2)
        for frame in (first,second):
            self.assertIn(f'Content-Length: {len(frame)}\r\n\r\n'.encode()+frame+b'\r\n',body)
        self.assertTrue(all(0<=seconds<=1/60 for seconds in waits))
        handler.send_header.assert_any_call('Content-Type','multipart/x-mixed-replace; boundary=camera-frame')
        self.assertTrue(handler.close_connection)


if __name__=='__main__':
    unittest.main()
