import tempfile
from pathlib import Path
from unittest import TestCase
from clear_t7 import clear_contents,MARKER

class ClearT7Tests(TestCase):
    def test_clears_only_volume_contents_and_never_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);volume=root/'volume';volume.mkdir();outside=root/'outside';outside.mkdir()
            (outside/'keep').write_text('keep')
            (volume/MARKER).write_text('volume identity')
            (volume/'link').symlink_to(outside,target_is_directory=True)
            (volume/'sessions').mkdir();(volume/'sessions'/'video.mkv').write_bytes(b'recording')
            (volume/'Uploads').mkdir();(volume/'Uploads'/'tone.mp3').write_bytes(b'audio')
            clear_contents(volume,lambda:None)
            self.assertEqual([p.name for p in volume.iterdir()],[MARKER])
            self.assertEqual((outside/'keep').read_text(),'keep')
    def test_identity_failure_stops_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            volume=Path(temp);(volume/'keep').write_text('data')
            def reject():raise RuntimeError('wrong drive')
            with self.assertRaises(RuntimeError):clear_contents(volume,reject)
            self.assertTrue((volume/'keep').exists())
