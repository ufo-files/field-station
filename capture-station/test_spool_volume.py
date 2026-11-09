import os,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from spool_volume import require_spool_volume
class SpoolVolumeTests(unittest.TestCase):
 def test_missing_mount_never_creates_spool(self):
  from rolling_buffer import RollingBuffer
  with tempfile.TemporaryDirectory() as d:
   volume=Path(d)/'missing';root=volume/'spool';stop=threading.Event();stop.set()
   with patch.dict(os.environ,{'CAPTURE_SPOOL_VOLUME':str(volume),'CAPTURE_SPOOL_VOLUME_ID':'known'}):
    buffer=RollingBuffer(Path(d),stop,root=root)
    self.assertIsNotNone(buffer.error)
    with self.assertRaises(OSError):buffer.new_run()
    self.assertFalse(root.exists())
 def test_requires_correct_marker_and_contained_root(self):
  with tempfile.TemporaryDirectory() as d:
   volume=Path(d);(volume/'.field-spool-volume').write_text('known')
   with patch.dict(os.environ,{'CAPTURE_SPOOL_VOLUME':str(volume),'CAPTURE_SPOOL_VOLUME_ID':'known'}),patch.object(Path,'is_mount',return_value=True):
    self.assertEqual(require_spool_volume(volume/'spool'),volume)
    with self.assertRaises(OSError):require_spool_volume(volume.parent/'outside')
    (volume/'.field-spool-volume').write_text('wrong')
    with self.assertRaises(OSError):require_spool_volume(volume/'spool')
