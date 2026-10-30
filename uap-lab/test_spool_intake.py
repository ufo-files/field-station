import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import lab
from station_intake import import_session
class IntakeTests(unittest.TestCase):
 def test_waits_for_remux_without_launching_transcode(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);lab.save(folder/'manifest.json',dict(state='completed',buffered_capture=True,video_playback={'state':'queued'}));lab.save(folder/'buffer-state.json',{'state':'assembled'});(folder/'video.mkv').write_bytes(b'original')
   with patch.object(lab,'import_training_file') as importer:
    self.assertIsNone(import_session(folder));importer.assert_not_called()
 def test_reuses_ready_native_mp4(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/'session';folder.mkdir();target=Path(tmp)/'target';target.mkdir();lab.save(folder/'manifest.json',dict(state='completed',buffered_capture=True,video_playback={'state':'completed'}));lab.save(folder/'buffer-state.json',{'state':'assembled'});(folder/'video.mkv').write_bytes(b'original');(folder/'video.mp4').write_bytes(b'playback')
   with patch.object(lab,'import_training_file',return_value=({'id':'a'*32,'sha256':'sha','preview_state':'preparing'},True)),patch.object(lab,'video_path',return_value=target):
    result=import_session(folder)
   self.assertEqual(result['preview_state'],'ready');self.assertEqual((target/'preview.mp4').read_bytes(),b'playback')
