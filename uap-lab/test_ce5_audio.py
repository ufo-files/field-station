import tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from ce5_audio import Player

class PlaybackTests(unittest.TestCase):
 def test_missing_track_and_invalid_input(self):
  with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',{},clear=True):
   player=Player(root)
   self.assertFalse(player.status()['available'])
   with self.assertRaises(ValueError):player.set(True)
   with self.assertRaises(ValueError):player.set('true')
 def test_start_stop_and_completion(self):
  with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',{},clear=True):
   path=Path(root)/'audio/ce5.wav';path.parent.mkdir();path.touch()
   process=MagicMock();process.poll.return_value=None
   with patch('ce5_audio.subprocess.Popen',return_value=process) as launch:
    player=Player(root)
    self.assertTrue(player.set(True)['playing'])
    self.assertTrue(player.set(True)['playing']);self.assertEqual(launch.call_count,1)
    self.assertFalse(player.set(False)['playing']);process.terminate.assert_called_once()
    player.set(True);process.poll.return_value=0;process.returncode=0
    self.assertFalse(player.status()['playing'])
 def test_failed_playback_is_reported(self):
  with tempfile.TemporaryDirectory() as root:
   player=Player(root);player.process=MagicMock();player.process.poll.return_value=1;player.process.returncode=1
   self.assertIn('unexpectedly',player.status()['error'])
