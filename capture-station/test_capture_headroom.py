import tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from experiments import Experiments,save
from storage_recovery import update_pause

class CapturePriorityTests(unittest.TestCase):
 def test_background_has_no_hidden_reservation(self):
  e=object.__new__(Experiments);e.storage_reserve=lambda:80*1024**3
  self.assertEqual(e.background_reserve(),80*1024**3)
  self.assertFalse(update_pause({'available':True,'free':95*1024**3},e.storage_reserve(),{'paused':True})['paused'])
 def test_retired_session_is_not_prepared_again(self):
  with tempfile.TemporaryDirectory() as tmp:
   e=object.__new__(Experiments);e.data=Path(tmp);e.storage=lambda:{'available':True};e.queue_frames=Mock();e.queue_playback=Mock()
   p=e.data/'20261104T000000Z-abcdef';p.mkdir();(p/'video.mkv').touch()
   save(p/'manifest.json',{'id':p.name,'state':'completed','session_media_removed':True})
   e.resume_pending();e.queue_frames.assert_not_called();e.queue_playback.assert_not_called()

class NoReserveTests(unittest.TestCase):
 def test_zero_reserve_uses_available_space_and_recovers_without_ten_gib(self):
  state=update_pause({'available':True,'free':0},0)
  self.assertTrue(state['paused']);self.assertEqual(state['resume_bytes'],0)
  self.assertFalse(update_pause({'available':True,'free':1024**2},0,state)['paused'])
