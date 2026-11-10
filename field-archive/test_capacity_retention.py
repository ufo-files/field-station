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
            c.save(video/'annotations.json',[dict(id='a',label='not_anomalous',image='crop.png')]);(video/'crop.png').write_bytes(b'training crop')
            c.save(session/'archive-decision.json',dict(human_confirmed=False,checked_epoch=1))
            unit=c.inventory(root,'s');archive=root/'archive.tar'
            with tarfile.open(archive,'w') as t:
                for e in unit['files']:t.add(root/e['path'],arcname=e['path'])
            verify_archive(archive,unit)
            c.save(session/'archive-decision.json',dict(human_confirmed=False,checked_epoch=2))
            result=c.evict(root,unit,c.fingerprint(unit))
            self.assertEqual(c.read(session/'archive-decision.json')['checked_epoch'],2)
            self.assertEqual((video/'crop.png').read_bytes(),b'training crop');self.assertEqual(c.read(video/'annotations.json')[0]['label'],'not_anomalous')
            self.assertEqual(result['unlinked_files'],2);self.assertFalse((video/'source').exists());self.assertTrue((session/'manifest.json').exists())
            self.assertTrue(c.read(video/'video.json')['media_expired']);self.assertEqual(c.read(root/'uap-lab/provisional-queue/s.json')['state'],'archived')
            verify_archive(archive,unit)
    def test_retired_and_deleted_reviews_do_not_pin_recordings(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for i,flags in enumerate((dict(retired=True),dict(deleted=True),dict())):
                c.save(root/f'uap-lab/email-reviews/examples/{i}/review.json',dict(label='anomalous',human_confirmed=True,generation='run-'+str(i),pts_seconds=1,**flags))
            self.assertEqual(c.protection_snapshot(root)[1],{'run-2':[1]})
    def test_compact_review_index_protects_anomalies_without_per_crop_scan(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);c.save(root/'uap-lab/email-reviews/training-manifest.json',dict(examples=[dict(generation='a',pts_seconds=1,label='anomalous',human_confirmed=True),dict(generation='b',pts_seconds=2,label='not_anomalous',human_confirmed=True)]))
            with patch.object(Path,'glob',side_effect=lambda pattern: [] if pattern in ('*/run.json','*/video.json') else (_ for _ in ()).throw(AssertionError('Unexpected crop scan'))):
                self.assertEqual(c.protection_snapshot(root)[1],{'a':[1]})
    def test_malformed_review_index_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);c.save(root/'uap-lab/email-reviews/training-manifest.json',dict(examples=None))
            with self.assertRaises(ValueError):c.protection_snapshot(root)
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
            c.save(r/'uap-lab/videos/v/annotations.json',[dict(label='anomalous')])
            self.assertTrue(c.protected(r,'s'))
    def test_live_review_lease_blocks_offload_and_expires(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);c.save(root/'sessions/s/manifest.json',dict(capture_origin='provisional_motion',state='completed'))
            c.save(root/'uap-lab/videos/v/video.json',dict(provenance=dict(session_id='s')))
            c.save(root/'uap-lab/review-leases.json',dict(v=time.time()+900))
            self.assertTrue(c.protected(root,'s'))
            c.save(root/'uap-lab/review-leases.json',dict(v=time.time()-1))
            self.assertFalse(c.protected(root,'s'))
    def test_negative_crops_do_not_pin_source_but_mixed_and_active_reviews_do(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);c.save(r/'sessions/s/manifest.json',dict(capture_origin='provisional_motion',state='completed'))
            c.save(r/'uap-lab/videos/v/video.json',dict(provenance=dict(session_id='s')))
            p=r/'uap-lab/videos/v/annotations.json'
            for label in ('cloud','not_anomalous','bird'):
                c.save(p,[dict(label=label)]);self.assertFalse(c.protected(r,'s'))
            c.save(p,[dict(label='not_anomalous'),dict(label='anomalous')]);self.assertTrue(c.protected(r,'s'))
            c.save(p,[dict(label='unknown')]);self.assertTrue(c.protected(r,'s'))
            c.save(p,[dict(label='not_anomalous')]);c.save(r/'uap-lab/review-leases.json',dict(v=time.time()+900));self.assertTrue(c.protected(r,'s'))

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
    def test_metadata_refresh_never_excuses_changed_media(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);p=r/'video.mkv';p.write_bytes(b'original');st=p.stat()
            unit=dict(session='s',files=[dict(path='video.mkv',bytes=st.st_size,mtime_ns=st.st_mtime_ns,sha256=hashlib.sha256(b'original').hexdigest())]);p.write_bytes(b'changed!')
            with patch.object(c,'eligible',return_value=True):
                with self.assertRaisesRegex(ValueError,'Source changed'):c.verify_unchanged(r,unit,media_only=True)

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):c.checked(Path('/tmp/safe'),'../outside')

if __name__=='__main__':unittest.main()

class ReceiverProgressTests(unittest.TestCase):
    def test_review_race_does_not_abort_other_units_or_next_batch(self):
        import plistlib,shlex,subprocess
        from types import SimpleNamespace
        from capacity_receiver import run
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);states=iter([dict(offloading=True,free_bytes=1,candidates=['review-race','one']),dict(offloading=True,free_bytes=2,candidates=['two']),dict(offloading=False,free_bytes=3,candidates=[])]);evicted=[]
            def remote(args,stdout,**kwargs):
                command=shlex.split(args[-1]);action=command[2]
                if action=='status':return SimpleNamespace(stdout=json.dumps(next(states)).encode())
                sid=command[command.index('--session')+1]
                if sid=='review-race':raise subprocess.CalledProcessError(1,args)
                if action=='inventory':return SimpleNamespace(stdout=json.dumps(dict(session=sid,files=[])).encode())
                if action=='export':
                    with tarfile.open(fileobj=stdout,mode='w'):pass
                    return SimpleNamespace(stdout=None)
                if action=='evict':evicted.append(sid);return SimpleNamespace(stdout=b'{"unlinked_files": 1}')
                raise AssertionError(action)
            cfg=dict(archive_volume=str(root),archive_uuid='uuid',archive_reserve_gib=0,field_python='python',field_script='retention.py',local_python='python',ssh_helper='ssh.py')
            with patch('capacity_receiver.subprocess.check_output',return_value=plistlib.dumps(dict(VolumeUUID='uuid'))),patch.object(Path,'is_mount',return_value=True),patch('capacity_receiver.subprocess.run',side_effect=remote):run(cfg)
            self.assertEqual(evicted,['one','two'])
            status=json.loads((root/'field-archive/status.json').read_text());self.assertEqual(len(status['errors']),1);self.assertFalse(status['field']['offloading'])

class StorageAliasTests(unittest.TestCase):
 def test_only_registered_verified_external_alias_is_accepted(self):
  from unittest.mock import patch
  from capacity_retention import checked
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);root=base/'source';volume=base/'external';root.mkdir();volume.mkdir();target=volume/'spool';target.mkdir()
   (root/'capture-spool').symlink_to(target,target_is_directory=True)
   with self.assertRaises(ValueError):checked(root,'capture-spool/run-a')
   (volume/'.field-spool-volume').write_text('known')
   (root/'retention-policy.json').write_text(json.dumps(dict(storage_aliases={'capture-spool':dict(volume=str(volume),target=str(target),identity='known')})))
   with patch.object(Path,'is_mount',return_value=True):
    self.assertEqual(checked(root,'capture-spool/run-a'),root/'capture-spool/run-a')
    (target/'escape').symlink_to(base)
    with self.assertRaises(ValueError):checked(root,'capture-spool/escape/file')
    (volume/'.field-spool-volume').write_text('wrong')
    with self.assertRaises(ValueError):checked(root,'capture-spool/run-a')

 def test_completed_generation_alias_requires_exact_registration(self):
  from unittest.mock import patch
  from capacity_retention import checked
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);root=base/'source';volume=base/'external';root.mkdir();volume.mkdir()
   (root/'capture-spool').mkdir();target=volume/'run-a';target.mkdir()
   link=root/'capture-spool/run-a';link.symlink_to(target,target_is_directory=True)
   (volume/'.field-spool-volume').write_text('known')
   spec=dict(volume=str(volume),target=str(target),identity='known')
   policy=root/'retention-policy.json'
   policy.write_text(json.dumps(dict(storage_aliases={'capture-spool':spec})))
   with patch.object(Path,'is_mount',return_value=True):
    with self.assertRaises(ValueError):checked(root,'capture-spool/run-a/segment.mkv')
    policy.write_text(json.dumps(dict(storage_aliases={'capture-spool/run-a':spec})))
    self.assertEqual(checked(root,'capture-spool/run-a/segment.mkv'),link/'segment.mkv')
    (target/'escape').symlink_to(base)
    with self.assertRaises(ValueError):checked(root,'capture-spool/run-a/escape/file')
    with self.assertRaises(ValueError):checked(root,'capture-spool/run-a/../run-b')
    with patch.object(Path,'is_mount',return_value=False):
     with self.assertRaises(ValueError):checked(root,'capture-spool/run-a/segment.mkv')
