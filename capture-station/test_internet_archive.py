import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
from experiments import save,load,file_info
from internet_archive import InternetArchive,ArchiveAPI,ArchiveError,hashes

SID='20261027T010933Z-824761'

class FakeAPI:
    def __init__(self):self.remote={};self.parts={};self.parts_by_file={};self.calls=[];self.available=True;self.fail_part_once=False;self.fail_complete_once=False;self.completed=set()
    def configured(self):return True
    def small(self,job,entry,path):self.remote[entry['name']]=dict(name=entry['name'],size=str(entry['bytes']),md5=entry['md5']);self.calls.append(('small',entry['name']))
    def initiate(self,job,entry):return 'upload-'+entry['name']
    def part(self,job,entry,upload_id,number,data):
        self.parts[number]=data;self.calls.append(('part',number))
        self.parts_by_file.setdefault(entry['name'],{})[number]=data
        if self.fail_part_once:self.fail_part_once=False;raise ArchiveError(0,'test lost part response')
        return 'etag-'+str(number)
    def complete(self,job,entry,upload_id,parts):
        if entry['name'] in self.completed:raise ArchiveError(404,'NoSuchUpload')
        self.remote[entry['name']]=dict(name=entry['name'],size=str(entry['bytes']),md5=entry['md5']);self.completed.add(entry['name'])
        if self.fail_complete_once:self.fail_complete_once=False;raise ArchiveError(0,'test lost commit response')
    def metadata(self,identifier):return dict(metadata=dict(identifier=identifier),files=list(copy.deepcopy(self.remote).values()))
    def downloadable(self,job,entry):return self.available

class ArchiveTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'ssd/sessions';self.folder=self.data/SID;self.folder.mkdir(parents=True)
        (self.folder/'video.mp4').write_bytes(b'encoded video source with enough bytes for several parts')
        (self.folder/'video-annotated.mp4').write_bytes(b'boxed frames')
        self.decision=dict(schema=2,source='station_web_ui',session_id=SID,human_confirmed=True,confirmed_anomalous=True,bundle_ready=True,videos=['video.mp4','video-annotated.mp4'],reviewed_epoch=time.time(),review_revision='one')
        save(self.folder/'archive-decision.json',self.decision)
        (self.folder/'video.mkv').write_bytes(b'original camera packets')
        (self.folder/'rf.jsonl').write_text('RF evidence')
        (self.folder/'frames').mkdir();(self.folder/'frames/frame-000000000.jpg').write_bytes(b'original selected JPEG')
        save(self.folder/'frames/index.json',dict(mode='selected',frames=[dict(file='frame-000000000.jpg',**file_info(self.folder/'frames/frame-000000000.jpg'))]))
        self.motion=self.folder/'motion-0123456789abcdef-before.jpg';self.motion.write_bytes(b'original trigger JPEG')
        self.m=dict(id=SID,capture_origin='manual',state='completed',frames=dict(state='completed',mode='selected',count=1),video_playback=dict(state='completed',frame_count=120),files={'video.mp4':file_info(self.folder/'video.mp4'),'video.mkv':file_info(self.folder/'video.mkv')})
        save(self.folder/'manifest.json',self.m)
        self.yt=SimpleNamespace(busy=lambda _:False,current=None,frames_present=lambda *_:True,job_cache={},persist=Mock(),publish=Mock())
        self.station=SimpleNamespace(lock=threading.RLock(),exiting=threading.Event(),youtube=self.yt)
        self.storage=lambda:dict(available=True,free=10**11)
        self.api=FakeAPI();self.a=InternetArchive(self.station,self.root/'app',self.data,self.storage,api=self.api,start=False)
        self.a.discover();self.job=self.a.job_cache[SID]
    def tearDown(self):self.tmp.cleanup()
    def upload(self):
        with patch('internet_archive.PART_SIZE',8):
            for _ in range(50):
                if self.job['state']=='verifying':return
                self.a.send(self.job);self.a.persist(self.job)
        self.fail('Upload did not finish')
    def test_both_videos_required_and_multiple_targets_still_one_item(self):
        self.a.discover();self.assertEqual(len(self.a.job_cache),1)
        self.a.job_cache.clear();(self.folder/'video-annotated.mp4').unlink();self.a.discover();self.assertFalse(self.a.job_cache)
    def test_annotated_download_required_to_verify(self):
        self.upload()
        self.api.downloadable=lambda job,entry:entry['name']!='video-annotated.mp4'
        self.assertFalse(self.a.verify(self.job));self.assertFalse(self.job.get('verified_at'))
    def test_updated_boxes_refresh_same_item_and_revoke_verification(self):
        self.upload();self.a.verify(self.job)
        identifier=self.job['identifier'];(self.folder/'video-annotated.mp4').write_bytes(b'new reviewed boxes')
        save(self.folder/'archive-decision.json',dict(self.decision,review_revision='two'))
        self.assertTrue(self.a.complete_session_plan(self.job,self.m))
        self.assertEqual(self.job['identifier'],identifier);self.assertFalse(self.job.get('verified_at'))
        self.assertEqual(self.job['state'],'uploading')
    def test_restored_session_can_bypass_stale_assembly_queue_but_not_active_work(self):
        self.a.job_cache.clear();self.yt.busy=lambda _:True
        self.station.experiments=SimpleNamespace(assembly_pending={SID})
        save(self.folder/'buffer-state.json',dict(state='assembled',restored_by_archive=True))
        self.a.discover();self.assertIn(SID,self.a.job_cache)
        self.a.job_cache.clear();self.station.experiments.assembly_processing=SID
        self.a.discover();self.assertFalse(self.a.job_cache)
    def test_verified_upload_retains_then_deletes_only_video(self):
        self.upload();self.assertTrue(self.a.verify(self.job));self.a.persist(self.job)
        self.assertTrue(self.a.verified(SID,next(e for e in self.job['files'] if e['name']=='video.mp4')['sha256']))
        self.a.cleanup(self.job);self.assertTrue((self.folder/'video.mp4').exists())
        self.job['verified_at']=time.time()-3601
        self.a.cleanup(self.job)
        self.assertEqual(self.job['state'],'cleaned')
        self.assertFalse((self.folder/'video.mp4').exists());self.assertFalse((self.folder/'video.mkv').exists())
        for p in (self.motion,self.folder/'rf.jsonl',self.folder/'frames/frame-000000000.jpg'):self.assertTrue(p.exists())
        self.assertEqual(load(self.folder/'manifest.json')['video_playback']['state'],'internet_archive')
        self.assertTrue((self.a.catalog/(SID+'.json')).exists())
    def test_complete_session_plan_has_native_archive_inventory_and_logs(self):
        (self.folder/'capture.log').write_text('Capture evidence')
        save(self.folder/'buffer-state.json',dict(state='assembled',timing='UTC capture timing'))
        (self.folder/'video-assembling.mkv').write_bytes(b'raw scratch packets')
        # Model an older item that needs supplemental session files.
        self.job['plan_version']=1;self.a.complete_session_plan(self.job,self.m)
        names={e['name'] for e in self.job['files']}
        self.assertTrue({'capture.log','buffer-state.json','manifest.json','archive-index.json','video.mp4'}.issubset(names))
        self.assertIn('video.mkv',names);self.assertNotIn('video-assembling.mkv',names)
        inventory=next(e for e in self.job['files'] if e['name']=='archive-index.json')
        self.assertIn('video.mp4',[e['name'] for e in load(self.a.source(self.job,inventory))['files']])

    def test_extending_verified_item_holds_cleanup_until_new_files_verify(self):
        self.upload();self.a.verify(self.job);self.a.persist(self.job)
        old_length=len(self.job['files']);self.job['plan_version']=1
        (self.folder/'capture.log').write_text('Additional capture log')
        self.assertTrue(self.a.complete_session_plan(self.job,self.m))
        self.assertEqual(self.job['state'],'uploading')
        self.assertEqual(self.job['files'][self.job['file_index']]['name'],'archive-index.json')
        self.assertFalse(self.job.get('verified_at'))
        self.assertTrue((self.folder/'video.mp4').exists())
        self.upload();self.assertTrue(self.a.verify(self.job))
        self.assertEqual(self.job['uploaded_bytes'],self.job['total_bytes'])

    def test_bad_checksum_or_unavailable_download_never_verifies(self):
        self.upload();self.api.remote['video.mp4']['md5']='0'*32
        self.assertFalse(self.a.verify(self.job));self.assertTrue((self.folder/'video.mp4').exists())
        self.api.remote['video.mp4']['md5']=next(e for e in self.job['files'] if e['name']=='video.mp4')['md5'];self.api.available=False
        self.assertFalse(self.a.verify(self.job));self.assertFalse(self.job.get('verified_at'))
    def test_missing_remote_sidecar_prevents_cleanup(self):
        self.upload();self.a.verify(self.job);self.job['verified_at']=time.time()-3601
        del self.api.remote['rf.jsonl']
        with self.assertRaises(ValueError):self.a.cleanup(self.job)
        self.assertTrue((self.folder/'video.mkv').exists())
    def test_lost_part_response_retries_same_part_without_duplicate_bytes(self):
        with patch('internet_archive.PART_SIZE',8):
            while not self.job.get('upload_id'):self.a.send(self.job);self.a.persist(self.job)
            self.api.fail_part_once=True
            with self.assertRaises(ArchiveError):self.a.send(self.job)
            self.a.persist(self.job)
            restored=InternetArchive(self.station,self.root/'app',self.data,self.storage,api=self.api,start=False)
            self.a=restored;self.job=restored.job_cache[SID]
            self.a.send(self.job);self.a.persist(self.job)
        self.upload()
        parts=self.api.parts_by_file['video.mp4']
        self.assertEqual(b''.join(parts[k] for k in sorted(parts)),(self.folder/'video.mp4').read_bytes())
    def test_lost_completion_response_can_verify_without_reupload(self):
        self.api.fail_complete_once=True
        with self.assertRaises(ArchiveError):self.upload()
        self.assertEqual(self.job['state'],'completing')
        self.a.complete(self.job);self.upload()
        self.assertEqual(self.job['state'],'verifying');self.assertTrue(self.a.verify(self.job))
    def test_mutated_local_video_or_symlink_never_gets_deleted(self):
        self.upload();self.a.verify(self.job);self.job['verified_at']=time.time()-3601
        (self.folder/'video.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.a.cleanup(self.job)
        self.assertTrue((self.folder/'video.mkv').exists())
    def test_unconfigured_waits_without_network_or_cleanup(self):
        self.api.configured=lambda:False;self.a.tick()
        self.assertEqual(self.a.phase,'waiting_credentials');self.assertFalse(self.api.calls)
    def test_uploaded_sources_and_keys_never_enter_public_snapshot(self):
        self.assertNotIn('credentials.json',[e['name'] for e in self.job['files']])
        body=json.dumps(self.a.status());self.assertNotIn('secret_key',body);self.assertNotIn('access_key',body)
    def test_source_change_stops_upload(self):
        entry=self.job['files'][0];self.a.source(self.job,entry).write_bytes(b'changed')
        with self.assertRaises(ValueError):self.a.send(self.job)
        self.assertFalse(self.api.calls)
    def test_cleanup_skips_unuploaded_youtube_mirror(self):
        self.yt.job_cache[SID]=dict(id=SID,state='queued')
        self.upload();self.a.verify(self.job);self.job['verified_at']=time.time()-3601;self.a.cleanup(self.job)
        self.assertEqual(self.yt.job_cache[SID]['state'],'skipped_archive_primary')

    def test_native_timestamps_all_selected_frames_and_model_evidence_are_archived(self):
        (self.folder/'buffer-segments').mkdir();(self.folder/'buffer-segments/frame-times-000000001.jsonl').write_text('{"pts": 16683}\n')
        (self.folder/'buffer-segments/segment-000000001.mkv').write_bytes(b'scratch')
        (self.folder/'model-frames').mkdir();(self.folder/'model-frames/object.png').write_bytes(b'original pixels')
        (self.folder/'model-frames/detections.jsonl').write_text('{}\n')
        for i in range(5):(self.folder/f'frames/frame-{i:09d}.jpg').write_bytes(b'selected object or boundary')
        self.job['plan_version']=2;self.a.complete_session_plan(self.job,self.m)
        names={entry['name'] for entry in self.job['files']}
        self.assertIn('buffer-segments/frame-times-000000001.jsonl',names)
        self.assertNotIn('buffer-segments/segment-000000001.mkv',names)
        self.assertIn('model-frames/detections.jsonl',names)
        self.assertIn('model-frames/object.png',names)
        self.assertIn('frames/frame-000000004.jpg',names)
        self.assertEqual(len(names),len(self.job['files']))

    def test_disabled_cleanup_keeps_offline_originals_after_verified_upload(self):
        self.upload();self.a.verify(self.job);self.job['verified_at']=time.time()-7200
        self.a.config['cleanup_enabled']=False;self.a.cleanup(self.job)
        self.assertTrue((self.folder/'video.mkv').is_file());self.assertTrue((self.folder/'video.mp4').is_file())
        self.assertEqual(self.job['state'],'retaining')

    def test_native_archive_uses_a_separate_multipart_upload(self):
        self.upload()
        self.assertEqual(self.api.completed,{'video.mp4','video.mkv','video-annotated.mp4'})
        self.assertNotIn('upload_id',self.job)

class CredentialsTests(TestCase):
    def test_keys_are_private_and_never_exposed_by_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            api=ArchiveAPI(Path(tmp));api.configure(dict(access_key='test-access-key',secret_key='test-secret-key'))
            self.assertEqual((Path(tmp)/'credentials.json').stat().st_mode&0o777,0o600)
            self.assertTrue(api.configured())
    def test_redirect_to_external_host_never_receives_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            api=ArchiveAPI(Path(tmp));api.configure(dict(access_key='test-access-key',secret_key='test-secret-key'))
            response=SimpleNamespace(status_code=307,headers={'Location':'https://outside.example/upload'},close=Mock())
            api.session.request=Mock(return_value=response)
            with self.assertRaises(ValueError):api.raw('PUT','https://s3.us.archive.org/test/video.mp4',b'bytes',auth=True)
            self.assertEqual(api.session.request.call_count,1)
