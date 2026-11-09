import io
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from broadcast_camera import CameraPipe, mjpeg_frames
from broadcast_rf import SpectrumOverlay
from youtube_broadcast import broadcast_args

class BroadcastTests(unittest.TestCase):
    def camera(self):
        camera = CameraPipe('http://127.0.0.1:8090/preview.mjpeg', Path(__file__).with_name('assets') / 'broadcast-standby.jpg')
        self.addCleanup(camera.close)
        # The production writer normally owns this end.
        import os
        self.addCleanup(os.close, camera.writer)
        camera.detector = Mock()
        camera.detector.matches.return_value = False
        return camera

    def test_camera_starts_on_standby_then_recovers_and_expires(self):
        camera = self.camera()
        self.assertEqual(camera.current(10), (camera.standby, True))
        camera.accept(b'live', 10)
        self.assertEqual(camera.current(12), (b'live', False))
        self.assertEqual(camera.current(13), (camera.standby, True))
        camera.accept(b'recovered', 14)
        self.assertEqual(camera.current(14), (b'recovered', False))

    def test_hdmi_no_signal_replaces_continuing_camlink_frames(self):
        camera = self.camera()
        camera.detector.matches.return_value = True
        camera.accept(b'elgato', 10)
        self.assertTrue(camera.current(10)[1])
        camera.detector.matches.return_value = False
        camera.accept(b'camera', 11)
        self.assertEqual(camera.current(11), (b'camera', False))

    def test_multipart_truncation_and_limit(self):
        jpeg = b'\xff\xd8test\xff\xd9'
        header = b'--camera-frame\r\nContent-Type: image/jpeg\r\nContent-Length: 8\r\n\r\n'
        self.assertEqual(list(mjpeg_frames(io.BytesIO(header + jpeg + b'\r\n'))), [jpeg])
        self.assertEqual(list(mjpeg_frames(io.BytesIO(header + jpeg[:3]))), [])
        with self.assertRaises(ValueError):
            list(mjpeg_frames(io.BytesIO(header.replace(b'Length: 8', b'Length: 999999999'))))

    def test_overlay_remains_visible_on_standby_with_station_green(self):
        renderer = SpectrumOverlay()
        data = {'receivers': {role: {'timestamp':100, 'range_hz':[1e6,6000e6], 'maximum_db':[-80]*600} for role in ('narrow','wide')}}
        live = renderer.render(data, Image.new('RGB',(1280,720),'white'), now=100)
        standby = renderer.render(data, now=100, standby=True)
        self.assertNotEqual(live.tobytes(), standby.tobytes())
        self.assertGreater(standby.getchannel('A').getextrema()[1], 0)
        self.assertEqual(renderer.render([], now=100).size, (340,182))

    def test_encoder_keeps_camera_and_rf_on_independent_inputs(self):
        config = {'publish_url':'rtmps://a.rtmps.youtube.com/live2/test-key','source':'http://127.0.0.1:8090/preview.mjpeg'}
        args = broadcast_args(config, 18, True, 17)
        self.assertIn('pipe:17', args)
        self.assertIn('pipe:18', args)
        self.assertNotIn(config['source'], args)
        self.assertNotIn(config['publish_url'], args)
        self.assertIn('eof_action=repeat', args[args.index('-filter_complex')+1])
        self.assertEqual(args[-3:], ['-f','null','-'])

if __name__ == '__main__':
    unittest.main()
