import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import server

class CapturePauseTests(unittest.TestCase):
 def test_pause_resume_preserves_session_and_preview(self):
  with tempfile.TemporaryDirectory() as d, patch.object(server,'RUN',Path(d)):
   station=object.__new__(server.Station);station.lock=threading.RLock();station.capture_control_lock=threading.RLock();station.buffer=SimpleNamespace(root=Path(d));station.capture_paused=False;station.active={'id':'saved-session'}
   station.stop=Mock();station.stop_camera=Mock();station.spawn_camera=Mock()
   self.assertEqual(station.set_capture_paused({'paused':True}),{'paused':True,'pending':True})
   self.assertTrue(json.loads((Path(d)/'capture-control.json').read_text())['paused'])
   station.stop.assert_not_called();station.spawn_camera.assert_not_called()
   station.set_capture_paused({'paused':True});station.spawn_camera.assert_not_called()
   station.active=None;station.set_capture_paused({'paused':False})
   self.assertFalse(json.loads((Path(d)/'capture-control.json').read_text())['paused'])
   station.spawn_camera.assert_not_called()
 def test_rejects_ambiguous_pause_values(self):
  station=object.__new__(server.Station)
  for value in (None,'false',0,1):
   with self.assertRaises(ValueError):station.set_capture_paused({'paused':value})

if __name__=='__main__':unittest.main()
