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
 def test_start_stop_and_loop(self):
  with tempfile.TemporaryDirectory() as root,patch.dict('os.environ',{},clear=True):
   path=Path(root)/'audio/ce5.wav';path.parent.mkdir();path.touch()
   process=MagicMock();process.poll.return_value=None
   with patch('ce5_audio.subprocess.Popen',return_value=process) as launch,patch('ce5_audio.threading.Thread.start'):
    player=Player(root)
    self.assertTrue(player.set(True)['playing'])
    self.assertTrue(player.set(True)['playing']);self.assertEqual(launch.call_count,1)
    self.assertFalse(player.set(False)['playing']);process.terminate.assert_called_once()
    player.set(True);process.poll.return_value=0;process.returncode=0
    next_process=MagicMock();next_process.poll.return_value=None;launch.return_value=next_process
    self.assertTrue(player.status()['playing']);self.assertIs(player.process,next_process)
    self.assertEqual(launch.call_count,3)
    player.set(False);next_process.terminate.assert_called_once()
    self.assertFalse(player.status()['playing']);self.assertEqual(launch.call_count,3)
 def test_failed_playback_is_reported(self):
  with tempfile.TemporaryDirectory() as root:
   player=Player(root);player.process=MagicMock();player.process.poll.return_value=1;player.process.returncode=1
   self.assertIn('unexpectedly',player.status()['error'])

 def test_stop_at_track_boundary_does_not_restart(self):
  with tempfile.TemporaryDirectory() as root,patch('ce5_audio.subprocess.Popen') as launch:
   player=Player(root);process=MagicMock();process.poll.return_value=0;process.returncode=0;player.process=process
   self.assertFalse(player.set(False)['playing']);launch.assert_not_called()
 def test_worker_loops_without_browser_polling(self):
  with tempfile.TemporaryDirectory() as root,patch('ce5_audio.time.sleep'),patch('ce5_audio.threading.Thread.start'),patch('ce5_audio.subprocess.Popen') as launch:
   player=Player(root);player.track=Path(root)/'ce5.mp3';old=MagicMock();old.poll.return_value=0;old.returncode=0;player.process=old
   new=MagicMock();new.poll.return_value=None;launch.return_value=new
   player.watch(old,1)
   self.assertIs(player.process,new);launch.assert_called_once();player.set(False)
