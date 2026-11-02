import hashlib,json,os,tarfile,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import capacity_retention as c
from capacity_receiver import verify_archive

class CapacityTests(unittest.TestCase):
    def test_verified_archive_precedes_media_eviction_and_keeps_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);session=root/'sessions/s';session.mkdir(parents=True)
            c.save(session/'manifest.json',dict(capture_origin='provisional_motion',state='completed',spool_generation='run-a',stopped_epoch=time.time()-600))
            os.utime(session/'manifest.json',(time.time()-600,time.time()-600))
            c.save(session/'buffer-state.json',dict(state='assembled',segments=[dict(start=0,end=10)]))
            for name in ('analysis-ack.json','recognition-ack.json'):c.save(root/'capture-spool/run-a'/name,dict(generation='run-a',integrity_ok=True,last_pts_seconds=10))
            video=root/'uap-lab/videos/v';c.save(video/'video.json',dict(provenance=dict(session_id='s')))
            (video/'source').write_bytes(b'native recording');(session/'video.mkv').write_bytes(b'original capture')
            unit=c.inventory(root,'s');archive=root/'archive.tar'
            with tarfile.open(archive,'w') as t:
                for e in unit['files']:t.add(root/e['path'],arcname=e['path'])
            verify_archive(archive,unit)
            result=c.evict(root,unit,c.fingerprint(unit))
            self.assertEqual(result['unlinked_files'],2);self.assertFalse((video/'source').exists());self.assertTrue((session/'manifest.json').exists())
            self.assertTrue(c.read(video/'video.json')['media_expired']);self.assertEqual(c.read(root/'uap-lab/provisional-queue/s.json')['state'],'archived')
            verify_archive(archive,unit)
    def test_hysteresis(self):
        p=dict(offload_used_fraction=.7,target_used_fraction=.6)
        self.assertFalse(c.pressure(100,31,False,p));self.assertTrue(c.pressure(100,30,False,p))
        self.assertTrue(c.pressure(100,35,True,p));self.assertFalse(c.pressure(100,40,True,p))
    def test_no_receipt_no_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);file=root/'evidence.mkv';file.write_bytes(b'protected')
            with self.assertRaises(ValueError):c.evict(root,dict(session='test',files=[]),'bad')
            self.assertTrue(file.exists())
    def test_manual_and_reviewed_protected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);p=r/'sessions/s/manifest.json';c.save(p,dict(capture_origin='manual',state='completed'))
            self.assertTrue(c.protected(r,'s'))
            c.save(p,dict(capture_origin='provisional_motion',state='completed'))
            c.save(r/'uap-lab/videos/v/video.json',dict(provenance=dict(session_id='s')))
            c.save(r/'uap-lab/videos/v/annotations.json',[dict(label='bird')])
            self.assertTrue(c.protected(r,'s'))
    def test_live_review_lease_blocks_offload_and_expires(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);c.save(root/'sessions/s/manifest.json',dict(capture_origin='provisional_motion',state='completed'))
            c.save(root/'uap-lab/videos/v/video.json',dict(provenance=dict(session_id='s')))
            c.save(root/'uap-lab/review-leases.json',dict(v=time.time()+900))
            self.assertTrue(c.protected(root,'s'))
            c.save(root/'uap-lab/review-leases.json',dict(v=time.time()-1))
            self.assertFalse(c.protected(root,'s'))
    def test_archive_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);f=r/'source';f.write_bytes(b'data');t=r/'archive.tar'
            with tarfile.open(t,'w') as archive:archive.add(f,arcname='source')
            u=dict(files=[dict(path='source',bytes=4,sha256=hashlib.sha256(b'data').hexdigest())]);verify_archive(t,u)
            u['files'][0]['sha256']='wrong'
            with self.assertRaises(ValueError):verify_archive(t,u)
    def test_new_review_blocks_eviction(self):
        with patch.object(c,'eligible',return_value=False):
            with self.assertRaisesRegex(ValueError,'protected'):c.verify_unchanged(Path('/unused'),dict(session='s',files=[]))
    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):c.checked(Path('/tmp/safe'),'../outside')

if __name__=='__main__':unittest.main()
