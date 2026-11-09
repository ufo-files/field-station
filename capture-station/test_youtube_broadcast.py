import io
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from broadcast_camera import CameraPipe, mjpeg_frames
from broadcast_rf import SpectrumOverlay, OverlayPipe
from broadcast_tags import visible_objects, TagOverlay
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

    def test_continuous_encoder_has_no_duration_limit_and_only_silent_audio(self):
        config = {'publish_url':'rtmps://a.rtmps.youtube.com/live2/test-key','source':'http://127.0.0.1:8090/preview.mjpeg','continuous':True}
        args = broadcast_args(config,18,camera_fd=17)
        self.assertNotIn('-t',args)
        self.assertIn('anullsrc=channel_layout=stereo:sample_rate=44100',args)
        self.assertEqual(args[args.index('-c:v')+1],'libx264')
        self.assertEqual(args[args.index('-nal-hrd')+1],'cbr')
        self.assertEqual(args[args.index('-minrate')+1],'4000k')
        self.assertEqual(args[args.index('-maxrate')+1],'4000k')
        self.assertEqual(args[args.index('-threads')+1],'2')
        self.assertEqual(args[args.index('-b:v')+1],'4000k')
        self.assertNotIn('avfoundation',args)

class BoundedValidationTests(unittest.TestCase):
    def test_validation_overrides_continuous_production_configuration(self):
        import json, tempfile
        from unittest.mock import patch
        import youtube_broadcast
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'encoder.json'
            config.write_text(json.dumps({'publish_url':'rtmps://a.rtmps.youtube.com/live2/test-key','source':'http://127.0.0.1:8090/preview.mjpeg','continuous':True}))
            with patch('sys.argv',['youtube_broadcast','--config',str(config),'--validate','--seconds','4']), patch.object(youtube_broadcast,'CameraPipe') as camera, patch.object(youtube_broadcast,'OverlayPipe') as overlay, patch.object(youtube_broadcast.subprocess,'Popen',side_effect=RuntimeError('stop before launching')) as popen:
                camera.return_value.reader=17;overlay.return_value.reader=18
                with self.assertRaisesRegex(RuntimeError,'stop before launching'):
                    youtube_broadcast.main()
                args=popen.call_args.args[0]
                self.assertIn('-t',args)
                self.assertEqual(args[-3:],['-f','null','-'])

class TagTests(unittest.TestCase):
    def state(self):
        return {'inference_epoch':100,'width':1920,'height':1080,'objects':[
            {'label':'anomalous','box':[150,150,300,150],'confirmed':True},
            {'label':'not_anomalous','box':[1000,200,100,100]},
            {'label':'anomalous','source':'display_only','box':[1200,200,100,100]}]}

    def test_only_anomalous_model_objects_are_drawn(self):
        state=self.state()
        objects=visible_objects(state,101)
        self.assertEqual(len(objects),1)
        image=TagOverlay().draw(Image.new('RGBA',(1280,720)),state,101)
        self.assertEqual(image.getpixel((100,100)),(145,255,218,255))
        self.assertEqual(image.getpixel((700,150))[3],0)

    def test_stale_future_and_standby_annotations_are_hidden(self):
        state=self.state()
        self.assertEqual(visible_objects(state,103),[])
        self.assertEqual(visible_objects(state,99),[])
        self.assertEqual(visible_objects(state,101,standby=True),[])
        state['camera_no_signal']=True
        self.assertEqual(visible_objects(state,101),[])

    def test_native_tags_require_a_matching_fresh_camera_frame(self):
        state={'display_epoch':100,'frame_epoch':100.1,'display_tags':[{'label':'anomalous','box':[100,200,300,400]}]}
        self.assertEqual(len(visible_objects(state,100.2)),1)
        state['frame_epoch']=101
        self.assertEqual(visible_objects(state,100.2),[])
        state['frame_epoch']=100.1
        self.assertEqual(visible_objects(state,100.6),[])

    def test_bad_boxes_cannot_break_the_stream(self):
        state=self.state()
        state['objects']=[{'label':'anomalous','box':box} for box in [[0,0,-1,2],[float('nan'),0,1,2],[2000,0,1,2],[1,2],None]]
        self.assertEqual(visible_objects(state,101),[])

    def test_full_frame_pipe_retains_rf_and_can_draw_annotations(self):
        import os
        pipe=OverlayPipe('/nonexistent')
        try:
            self.assertEqual(len(pipe.frame),1280*720*4)
            pipe.tags=self.state()
            canvas=pipe.compose(pipe.renderer.render({}))
            self.assertEqual(canvas.size,(1280,720))
            self.assertIsNotNone(canvas.crop((910,512,1250,694)).getbbox())
        finally:
            pipe.close();os.close(pipe.writer)

if __name__ == '__main__':
    unittest.main()
