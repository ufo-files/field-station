import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from experiments import save,load,file_info
from stills_archive import select_existing,prune_old_exports,StillsArchive

class StillsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.folder=self.root/'sessions/20261027T010933Z-824761';self.frames=self.folder/'frames';self.frames.mkdir(parents=True)
        self.export=self.frames/'export-0123456789';self.export.mkdir()
        entries=[]
        for i in range(10):
            p=self.export/f'frame-{i:09d}.jpg';p.write_bytes(b'original JPEG '+str(i).encode());entries.append(dict(file='export-0123456789/'+p.name,video_time_seconds=i,**file_info(p)))
        save(self.frames/'index.json',dict(frames=entries))
        (self.folder/'motion-0123456789abcdef-after.jpg').write_bytes(b'trigger evidence')
        (self.folder/'rf.jsonl').write_text('RF evidence')
    def tearDown(self):self.temp.cleanup()
    def test_selection_preserves_native_bytes_and_pruning_only_removes_exports(self):
        index=select_existing(self.folder)
        self.assertEqual([p['video_time_seconds'] for p in index['frames']],[0,5,9])
        self.assertEqual((self.frames/'frame-000000001.jpg').read_bytes(),b'original JPEG 5')
        self.assertEqual(len(list(self.export.glob('*.jpg'))),10)
        self.assertGreater(prune_old_exports(self.folder,index),0)
        self.assertFalse(self.export.exists())
        self.assertTrue((self.folder/'rf.jsonl').exists());self.assertTrue((self.folder/'motion-0123456789abcdef-after.jpg').exists())
    def test_changed_selected_still_prevents_pruning(self):
        index=select_existing(self.folder);(self.frames/index['frames'][0]['file']).write_bytes(b'changed')
        with self.assertRaises(ValueError):prune_old_exports(self.folder,index)
        self.assertTrue(self.export.exists())
    def test_failed_remote_push_never_prunes_original_exports(self):
        save(self.folder/'manifest.json',dict(id=self.folder.name,state='completed',frames=dict(state='completed',mode='all'),youtube=dict(verified_at=time.time()-7200)))
        station=SimpleNamespace(lock=threading.RLock(),exiting=threading.Event(),youtube=SimpleNamespace(busy=lambda _:False,storage=lambda:dict(available=True)))
        a=StillsArchive(station,self.root/'app',self.folder.parent,start=False);(a.repo/'.git').mkdir(parents=True)
        def fail_push(*args):
            if args[0]=='push':raise OSError('push failed')
            return 'changed' if args[0]=='status' else ''
        a.git=Mock(side_effect=fail_push)
        with self.assertRaises(OSError):a.tick()
        self.assertTrue(self.export.exists());self.assertFalse((a.receipts/(self.folder.name+'.json')).exists())

    def test_verified_push_prunes_only_after_retention(self):
        save(self.folder/'manifest.json',dict(id=self.folder.name,state='completed',frames=dict(state='completed',mode='all'),youtube=dict(verified_at=time.time()-7200)))
        station=SimpleNamespace(lock=threading.RLock(),exiting=threading.Event(),youtube=SimpleNamespace(busy=lambda _:False,storage=lambda:dict(available=True)))
        a=StillsArchive(station,self.root/'app',self.folder.parent,start=False);(a.repo/'.git').mkdir(parents=True)
        def git(*args):
            if args[0]=='rev-parse':return 'abc123'
            if args[0]=='ls-remote':return 'abc123 refs/heads/main'
            return ''
        a.git=Mock(side_effect=git);a.tick()
        self.assertFalse(self.export.exists())
        self.assertEqual(load(a.receipts/(self.folder.name+'.json'))['commit'],'abc123')
        self.assertTrue((self.folder/'rf.jsonl').exists())
        self.assertTrue((self.frames/'frame-000000000.jpg').exists())

if __name__=='__main__':unittest.main()
