import copy
import json
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
from experiments import save,load,file_info
from youtube_archive import YouTubeArchive,CHANNEL_ID
from youtube_api import YouTubeAPI,YouTubeError,upload_url

SID='20261027T010933Z-824761'
VID='testVideo_1'

class FakeAPI:
    def __init__(self):self.offset_bytes=0;self.finished=False;self.video=None;self.inits=0;self.fail_after_send=False
    def configured(self):return True
    def connected(self):return True
    def auth_status(self):return dict(configured=True,connected=True)
    def poll_auth(self):return False
    def channel(self,expected):return dict(id=expected,title='UFO Files Project')
    def initiate(self,metadata,size):self.inits+=1;return 'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test'
    def progress(self,url,size):
        if self.finished:return 201,{},dict(id=VID,snippet=dict(channelId=CHANNEL_ID))
        return 308,({'Range':f'bytes=0-{self.offset_bytes-1}'} if self.offset_bytes else {}),{}
    def offset(self,headers):return int(headers['Range'].split('-')[-1])+1 if headers.get('Range') else 0
    def chunk(self,url,offset,size,data):
        self.offset_bytes=offset+len(data);self.finished=True
        if self.fail_after_send:self.fail_after_send=False;raise OSError('Connection lost after final upload')
        return 201,{},dict(id=VID,snippet=dict(channelId=CHANNEL_ID))
    def list(self,resource,**params):return dict(items=[copy.deepcopy(self.video)] if self.video else [])

class ArchiveTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.data=self.root/'ssd/sessions';self.data.mkdir(parents=True)
        self.folder=self.data/SID;self.folder.mkdir();(self.folder/'video.mp4').write_bytes(b'encoded MP4 source')
        (self.folder/'video.mkv').write_bytes(b'native original packets')
        (self.folder/'rf.jsonl').write_text('RF evidence');(self.folder/'frames').mkdir();(self.folder/'frames/frame-000000000.jpg').write_bytes(b'frame')
        for i in range(1,60):(self.folder/f'frames/frame-{i:09d}.jpg').write_bytes(b'frame')
        save(self.folder/'frames/index.json',dict(frames=[dict(file=f'frame-{i:09d}.jpg',bytes=5) for i in range(60)]))
        (self.folder/'motion-event-after.jpg').write_bytes(b'evidence')
        self.m=dict(id=SID,state='completed',capture_origin='motion_trigger',title='Observation',
            frames=dict(state='completed',count=60),video_playback=dict(state='completed',frame_count=60,avg_frame_rate='60/1',width=160,height=90),
            files={'video.mp4':file_info(self.folder/'video.mp4'),'video.mkv':file_info(self.folder/'video.mkv')})
        save(self.folder/'manifest.json',self.m)
        exp=SimpleNamespace(queue_playback=Mock(),processing=None,assembly_processing=None,playback_processing=None,pending=set(),assembly_pending=set(),playback_priorities={})
        self.station=SimpleNamespace(lock=threading.RLock(),active=None,exiting=threading.Event(),experiments=exp)
        self.api=FakeAPI();self.a=YouTubeArchive(self.station,self.root/'app',self.data,lambda:dict(available=True,free=10**10),self.api,start=False)
        self.a.discover();self.job=load(self.a.jobs/(SID+'.json'))
        self.api.video=dict(id=VID,snippet=dict(channelId=CHANNEL_ID),status=dict(uploadStatus='processed',privacyStatus='public'),
            processingDetails=dict(processingStatus='succeeded'),fileDetails=dict(fileSize=self.job['source']['bytes'],videoStreams=[dict(widthPixels=160,heightPixels=90,frameRateFps=60)]))
    def test_status_includes_sessions_waiting_for_video_preparation(self):
        (self.a.jobs/(SID+'.json')).unlink()
        self.a.job_cache.clear()
        self.m['video_playback']=dict(state='queued')
        save(self.folder/'manifest.json',self.m)
        self.a.discover()
        self.assertEqual(self.a.status()['preparation_counts'],dict(preparing_video=1))
        self.assertEqual(self.a.status()['counts'],{})

    def test_retention_keeps_video_until_deadline(self):
        self.a.config['retention_seconds']=3600
        self.uploaded();self.a.verify(self.job)
        self.assertEqual(self.job['state'],'retaining')
        self.assertTrue((self.folder/'video.mkv').exists())
        self.assertTrue((self.folder/'video.mp4').exists())
        self.job['verified_at']=time.time()-3601
        self.a.cleanup(self.job)
        self.assertEqual(self.job['state'],'cleaned')
        self.assertFalse((self.folder/'video.mkv').exists())

    def test_stretched_remote_video_never_deletes_originals(self):
        self.uploaded()
        self.api.video['fileDetails']['videoStreams'][0]['aspectRatio']=256/81
        with self.assertRaisesRegex(ValueError,'aspect ratio mismatch'):
            self.a.verify(self.job)
        self.assertTrue((self.folder/'video.mkv').exists())
        self.assertTrue((self.folder/'video.mp4').exists())

    def test_primary_archive_requirement_holds_local_video_even_if_archive_paused(self):
        self.station.internet_archive=SimpleNamespace(verified=lambda *_:False,config=dict(enabled=False))
        self.uploaded();self.a.verify(self.job)
        self.assertEqual(self.job['state'],'waiting_archive')
        self.assertTrue((self.folder/'video.mp4').exists());self.assertTrue((self.folder/'video.mkv').exists())

    def tearDown(self):self.temp.cleanup()
    def uploaded(self):self.a.start_upload(self.job);self.a.send(self.job)
    def test_confirmed_upload_deletes_only_video_and_keeps_durable_metadata(self):
        self.uploaded();self.a.verify(self.job)
        self.assertEqual(self.job['state'],'cleaned')
        self.assertFalse((self.folder/'video.mp4').exists());self.assertFalse((self.folder/'video.mkv').exists())
        for name in ('rf.jsonl','frames/frame-000000000.jpg','motion-event-after.jpg','manifest.json'):self.assertTrue((self.folder/name).exists(),name)
        self.assertTrue((self.a.catalog/(SID+'.json')).exists())
        m=load(self.folder/'manifest.json');self.assertEqual(m['youtube']['video_id'],VID)
        self.assertIn('youtube.com/watch?',m['youtube']['url']);self.assertNotIn('video.mp4',m['files'])
        self.assertTrue(m['youtube']['cleanup_plan'])
    def test_processing_not_finished_keeps_all_video(self):
        self.uploaded();self.api.video['processingDetails']['processingStatus']='processing'
        self.a.verify(self.job);self.assertEqual(self.job['state'],'verifying');self.assertTrue((self.folder/'video.mkv').exists())
    def test_waits_for_frame_export_before_cleanup(self):
        self.uploaded();self.m['frames']['state']='queued';save(self.folder/'manifest.json',self.m)
        self.a.verify(self.job);self.assertEqual(self.job['state'],'waiting_frames');self.assertTrue((self.folder/'video.mp4').exists())
    def test_wrong_channel_visibility_size_or_fps_prevents_cleanup(self):
        self.uploaded();original=copy.deepcopy(self.api.video)
        changes=[lambda v:v['snippet'].update(channelId='wrong'),lambda v:v['status'].update(privacyStatus='private'),
            lambda v:v['fileDetails'].update(fileSize=9999),lambda v:v['fileDetails']['videoStreams'][0].update(frameRateFps=30)]
        for change in changes:
            self.api.video=copy.deepcopy(original);change(self.api.video)
            with self.assertRaises(ValueError):self.a.verify(self.job)
            self.assertTrue((self.folder/'video.mkv').exists())
    def test_unavailable_file_details_waits(self):
        self.uploaded();self.api.video['fileDetails']={};self.a.verify(self.job)
        self.assertEqual(self.job['state'],'verifying');self.assertTrue((self.folder/'video.mp4').exists())
    def test_upload_response_loss_recovers_without_duplicate_insert(self):
        self.a.start_upload(self.job);self.api.fail_after_send=True
        with self.assertRaises(OSError):self.a.send(self.job)
        restored=load(self.a.jobs/(SID+'.json'));self.a.send(restored)
        self.assertEqual(restored['video_id'],VID);self.assertEqual(self.api.inits,1)
    def test_expired_partially_sent_session_requires_review(self):
        self.a.start_upload(self.job);self.job['sent_any']=True
        self.api.progress=Mock(side_effect=YouTubeError(404,'notFound','Expired'))
        self.a.send(self.job);self.assertEqual(self.job['state'],'needs_review');self.assertEqual(self.api.inits,1)
        self.assertTrue((self.folder/'video.mp4').exists())
    def test_catalog_write_failure_prevents_first_delete(self):
        self.uploaded()
        with patch.object(self.a,'publish',side_effect=OSError('SD card write failed')):
            with self.assertRaises(OSError):self.a.verify(self.job)
        self.assertTrue((self.folder/'video.mp4').exists());self.assertTrue((self.folder/'video.mkv').exists())
    def test_symlink_or_busy_job_prevents_cleanup(self):
        self.uploaded();self.station.experiments.pending.add(SID);self.a.verify(self.job)
        self.assertTrue((self.folder/'video.mkv').exists())
        self.station.experiments.pending.clear();(self.folder/'video.mkv').unlink()
        outside=self.root/'outside';outside.write_bytes(b'keep');(self.folder/'video.mkv').symlink_to(outside)
        with self.assertRaises(ValueError):self.a.cleanup(self.job)
        self.assertEqual(outside.read_bytes(),b'keep')
    def test_cleanup_resumes_after_partial_unlink(self):
        self.uploaded();self.job.update(state='deleting',video_id=VID,verified_at=time.time())
        (self.folder/'video.mkv').unlink();self.a.cleanup(self.job)
        self.assertEqual(self.job['state'],'cleaned');self.assertTrue((self.folder/'frames/frame-000000000.jpg').exists())
    def test_no_duplicate_job_and_quota_retains_source(self):
        self.a.discover();self.assertEqual(len(list(self.a.jobs.glob('*.json'))),1)
        self.a.daily_available=lambda:('2026-10-27',100)
        self.a.start_upload(self.job);self.assertEqual(self.api.inits,0);self.assertTrue((self.folder/'video.mp4').exists())
    def test_status_does_not_expose_secrets_or_upload_location(self):
        self.a.start_upload(self.job)
        status=json.dumps(self.a.status());self.assertNotIn('upload_id',status);self.assertNotIn('upload_url',status)
    def test_refuses_session_symlink(self):
        outside=self.root/'outside-dir';outside.mkdir();(self.data/'20261027T010934Z-abcdef').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):self.a.session_folder('20261027T010934Z-abcdef')
    def test_missing_frame_retains_video_even_if_export_marked_complete(self):
        self.uploaded();(self.folder/'frames/frame-000000000.jpg').unlink()
        self.a.verify(self.job)
        self.assertEqual(self.job['state'],'waiting_frames')
        self.assertTrue((self.folder/'video.mkv').exists())


class APIValidationTests(TestCase):
    def test_resumable_url_cannot_leak_tokens_to_another_host(self):
        for url in ('http://www.googleapis.com/upload/youtube/v3/videos','https://evil.example/upload/youtube/v3/videos','https://www.googleapis.com/other'):
            with self.assertRaises(ValueError):upload_url(url)
    def test_oauth_credentials_require_client_not_password(self):
        with tempfile.TemporaryDirectory() as temp:
            api=YouTubeAPI(Path(temp))
            with self.assertRaises(ValueError):api.set_client(dict(username='user',password='not-oauth'))

    def test_testing_expiration_is_visible_without_exposing_token(self):
        from youtube_api import private_save
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);private_save(root/'token.json',dict(refresh_token='secret-refresh',access_token='secret-access',expires_in=3600,expires_at=time.time()+3600,refresh_token_expires_in=604800))
            api=YouTubeAPI(root);status=api.auth_status()
            self.assertTrue(status['connected']);self.assertGreater(status['refresh_expires_at'],time.time())
            self.assertNotIn('secret-',json.dumps(status))
