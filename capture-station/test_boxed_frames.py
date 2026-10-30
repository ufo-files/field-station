import os
from pathlib import Path
import tempfile
from unittest import TestCase
from boxed_frames import sync_boxed

class BoxedFrameTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
        self.sid='20261027T010933Z-824761';self.folder=self.data/self.sid;self.folder.mkdir()
        self.name='motion-0123456789abcdef-boxed.jpg';self.source=self.folder/self.name
        self.source.write_bytes(b'original boxed image')
        self.destination=self.data/'boxed-frames'/(self.sid+'--'+self.name)
    def tearDown(self):self.tmp.cleanup()
    def test_backfill_and_updated_annotation_are_independent_copies(self):
        self.assertEqual(sync_boxed(self.data),1)
        self.assertEqual(self.destination.read_bytes(),self.source.read_bytes())
        self.assertNotEqual(self.destination.stat().st_ino,self.source.stat().st_ino)
        self.assertEqual(sync_boxed(self.data),0)
        previous=self.source.stat().st_mtime_ns
        self.source.write_bytes(b'corrected boxed image');os.utime(self.source,ns=(previous+10**9,previous+10**9))
        self.assertEqual(sync_boxed(self.data),1);self.assertEqual(self.destination.read_bytes(),b'corrected boxed image')
        self.source.unlink();sync_boxed(self.data)
        self.assertTrue(self.destination.exists())
    def test_session_prefix_prevents_name_collisions(self):
        other=self.data/'20261027T020933Z-123456';other.mkdir();(other/self.name).write_bytes(b'another event')
        self.assertEqual(sync_boxed(self.data),2)
        self.assertEqual(len(list((self.data/'boxed-frames').glob('*.jpg'))),2)
    def test_symlink_destination_is_rejected_without_touching_target(self):
        other=self.data/'outside';other.mkdir();(self.data/'boxed-frames').symlink_to(other,target_is_directory=True)
        with self.assertRaises(ValueError):sync_boxed(self.data)
        self.assertEqual(list(other.iterdir()),[])
