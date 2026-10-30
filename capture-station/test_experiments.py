import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from experiments import Experiments, save, load


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root/'sessions'
        self.run = self.root/'run'
        self.data.mkdir()
        self.run.mkdir()
        self.station = SimpleNamespace(lock=threading.RLock(), active=None, exiting=threading.Event(),
                                       proc=Mock(), preview_age=lambda: 0, start=Mock(), stop=Mock())
        self.station.proc.poll.return_value = None
        self.e = Experiments(self.station, self.root, self.data, self.run, 'ffmpeg', {},
                             lambda: dict(available=True, free=10*1024**3),readrate=0)
        self.e.require_rf = Mock()
        self.e.validate_output = Mock()

    def tearDown(self):
        self.station.exiting.set()
        self.e.shutdown()
        self.temp.cleanup()

    def test_recovery_requeues_failed_preparation_but_skips_uploaded_and_recording(self):
        sid='20261026T000000Z-abcdef'
        folder=self.data/sid
        folder.mkdir()
        save(folder/'buffer-state.json',dict(segments=[dict(bytes=10)]))
        m=dict(id=sid,state='completed',frames=dict(state='failed'))
        save(folder/'manifest.json',m)
        with patch.object(self.e,'queue_frames') as queue_frames:
            self.e.resume_pending()
            queue_frames.assert_called_once_with(sid)
            queue_frames.reset_mock()
            m['youtube']=dict(state='cleaned')
            save(folder/'manifest.json',m)
            self.e.resume_pending()
            queue_frames.assert_not_called()
            m.pop('youtube');m['state']='recording'
            save(folder/'manifest.json',m)
            self.e.resume_pending()
            queue_frames.assert_not_called()

    def test_persistent_export_pause_survives_resume_request(self):
        (self.run/'exports-paused').write_text('Storage hold')
        proc=Mock();proc.poll.return_value=None
        self.e.large_assembly_proc=proc
        self.e.resume_exports()
        proc.send_signal.assert_not_called()
        proc.send_signal.reset_mock()
        def release():
            (self.run/'exports-paused').unlink()
        with patch.object(self.station.exiting,'wait',side_effect=lambda _:release()):
            self.e.io_gate(proc)
        import signal
        self.assertEqual(proc.send_signal.call_args_list,[unittest.mock.call(signal.SIGSTOP),unittest.mock.call(signal.SIGCONT)])
        self.e.large_assembly_proc=None

    def test_selected_stills_are_bounded_native_packets(self):
        import subprocess
        import server
        sid='20261026T000000Z-abcdef';folder=self.data/sid;folder.mkdir()
        source=folder/'video.mkv'
        subprocess.run([server.FFMPEG,'-hide_banner','-loglevel','error','-nostdin','-f','lavfi','-i','testsrc2=size=160x90:rate=30','-t','3','-c:v','mjpeg','-threads','1',str(source)],env=server.ENV,check=True)
        save(folder/'manifest.json',dict(id=sid,state='completed'))
        self.e.ffmpeg=server.FFMPEG;self.e.env=server.ENV
        index=self.e.prepare_selected_stills(folder,source,self.e.probe(source))
        self.assertEqual(len(index['frames']),3)
        self.assertEqual(len(list((folder/'frames').glob('*.jpg'))),3)
        self.assertEqual(load(folder/'manifest.json')['frames']['mode'],'selected')
        self.assertTrue(all((folder/'frames'/e['file']).read_bytes().startswith(bytes([255,216])) for e in index['frames']))

    def test_playback_overrides_incorrect_camera_pixel_aspect(self):
        import subprocess
        import server
        sid='20261026T000000Z-abcdef';folder=self.data/sid;folder.mkdir()
        source=folder/'video.mkv'
        subprocess.run([server.FFMPEG,'-hide_banner','-loglevel','error','-nostdin','-f','lavfi','-i','testsrc2=size=160x90:rate=30','-vf','setsar=16/9','-frames:v','30','-c:v','mjpeg','-threads','1',str(source)],env=server.ENV,check=True)
        save(folder/'manifest.json',dict(id=sid,state='completed',capture_stats=dict(frame=30)))
        self.e.ffmpeg=server.FFMPEG;self.e.env=server.ENV
        self.assertEqual(self.e.probe(source)['streams'][0]['sample_aspect_ratio'],'16:9')
        self.e.prepare_playback(folder)
        stream=self.e.probe(folder/'video.mp4')['streams'][0]
        self.assertEqual(stream['sample_aspect_ratio'],'1:1')
        self.assertEqual(stream['display_aspect_ratio'],'16:9')
        self.assertEqual((stream['width'],stream['height']),(160,90))

    def test_failed_playback_waits_for_retry_and_has_lower_priority(self):
        sid='20261026T000000Z-abcdef';folder=self.data/sid;folder.mkdir()
        (folder/'video.mkv').write_bytes(b'placeholder')
        manifest=dict(id=sid,state='completed',video_playback=dict(state='failed',attempts=1,next_attempt=time.time()+3600))
        save(folder/'manifest.json',manifest)
        self.e.playback_jobs=Mock();self.e.large_playback_jobs=Mock()
        self.e.queue_playback(sid)
        self.e.playback_jobs.put.assert_not_called()
        self.assertNotIn(sid,self.e.playback_priorities)
        manifest['video_playback']['next_attempt']=0;save(folder/'manifest.json',manifest)
        self.e.queue_playback(sid)
        self.assertEqual(self.e.playback_jobs.put.call_args.args[0][0],110)
        self.e.playback_priorities.clear()

    def test_background_media_has_lower_priority_than_parent(self):
        import os,subprocess
        before=os.getpriority(os.PRIO_PROCESS,0)
        proc=self.e.launch_media(['/usr/bin/sleep','2'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(os.getpriority(os.PRIO_PROCESS,proc.pid),10)
            self.assertEqual(os.getpriority(os.PRIO_PROCESS,0),before)
        finally:proc.terminate();proc.wait()

    def add_tone(self):
        self.e.assets.mkdir()
        (self.e.assets/'ce5.wav').write_bytes(b'fixture only, not real CE5 audio')
        save(self.e.assets/'ce5.json', {'name': 'test fixture'})

    def enable(self, **values):
        self.add_tone()
        body = dict(output='test-output', volume=25, ce5_enabled=True, duration_minutes=1, gap_minutes=0)
        body.update(values)
        self.e.enable(body)

    def manifest(self, condition='silence'):
        return dict(id='20261026T000000Z-abcdef', condition=condition, state='completed',
                    automatic_run='test-run', trial_valid=True)

    def test_missing_audio_prevents_enabling(self):
        with self.assertRaisesRegex(ValueError, 'Upload your CE5'):
            self.e.enable({'output': 'test-output', 'ce5_enabled': True})
        self.assertFalse(self.e.auto['enabled'])
        self.e.validate_output.assert_not_called()

    def test_unusable_speaker_prevents_enabling(self):
        self.add_tone()
        self.e.validate_output.side_effect = ValueError('No speaker')
        with self.assertRaisesRegex(ValueError, 'No speaker'):
            self.e.enable({'output': 'test-output', 'ce5_enabled': True})
        self.assertFalse(self.e.auto['enabled'])

    def test_enable_always_starts_with_one_minute_silence(self):
        self.enable()
        self.e.tick()
        body = self.station.start.call_args.args[0]
        self.assertEqual(body['condition'], 'silence')
        self.assertEqual(body['minutes'], 1)
        self.assertTrue(self.station.start.call_args.kwargs['automatic'])

    def test_ce5_waits_for_silent_session_frame_export(self):
        self.enable()
        manifest = self.manifest()
        folder = self.data/manifest['id']
        folder.mkdir()
        self.e.before_finalize(manifest, 'Automatic stop: duration reached')
        save(folder/'manifest.json', manifest)
        self.e.tick()
        self.station.start.assert_not_called()
        self.assertEqual(self.e.auto['phase'], 'extracting_frames')
        manifest['frames']['state'] = 'completed'
        save(folder/'manifest.json', manifest)
        self.e.tick()
        self.assertEqual(self.station.start.call_args.args[0]['condition'], 'ce5')

    def test_failed_frames_skip_pair_and_keep_schedule_enabled(self):
        self.enable()
        m = self.manifest()
        folder = self.data/m['id']
        folder.mkdir()
        self.e.before_finalize(m, 'Automatic stop: duration reached')
        m['frames']['state'] = 'failed'
        save(folder/'manifest.json', m)
        self.e.tick()
        self.assertTrue(self.e.auto['enabled'])
        self.assertEqual(self.e.auto['next_condition'],'silence')
        self.assertIsNone(self.e.auto['last_session'])
        self.station.start.assert_not_called()

    def test_failed_playback_invalidates_trial_and_stops(self):
        self.enable()
        m = self.manifest('ce5')
        m['started_monotonic'] = time.monotonic()
        self.station.active = m
        self.e.audio = Mock()
        self.e.audio.poll.return_value = 1
        self.e.audio.returncode = 1
        self.e.tick()
        self.assertFalse(m['trial_valid'])
        self.assertFalse(self.e.auto['enabled'])
        self.station.stop.assert_called_once_with('CE5 playback failed')
        self.e.audio = None

    def test_stale_rf_stops_trial_instead_of_running_without_signals(self):
        self.enable()
        self.station.active = self.manifest()
        self.e.require_rf.side_effect = ValueError('RF stale')
        self.e.tick()
        self.assertTrue(self.e.auto['enabled'])
        self.assertEqual(self.e.auto['phase'],'waiting_resources')
        self.assertFalse(self.station.active['trial_valid'])
        self.station.stop.assert_called_once()

    def test_one_pair_stops_after_ce5_and_frames(self):
        self.enable(repeat=False)
        m = self.manifest('ce5')
        folder = self.data/m['id']
        folder.mkdir()
        self.e.before_finalize(m, 'Automatic stop: duration reached')
        m['frames']['state'] = 'completed'
        save(folder/'manifest.json', m)
        self.e.tick()
        self.assertFalse(self.e.auto['enabled'])
        self.assertEqual(self.e.auto['phase'], 'completed')
        self.station.start.assert_not_called()

    def test_disable_stops_automatic_session(self):
        self.enable()
        self.station.active = self.manifest()
        self.e.disable()
        self.assertFalse(self.e.auto['enabled'])
        self.station.stop.assert_called_once_with('Automatic capture disabled by observer')

    def test_library_import_preserves_uploaded_original(self):
        uploads = self.root/'Uploads'
        uploads.mkdir()
        original = uploads/'Track 1.mp3'
        original.write_bytes(b'original audio fixture')
        def prepared(temporary, name):
            self.assertNotEqual(temporary, original)
            self.assertEqual(temporary.read_bytes(), original.read_bytes())
            return {'ready': True, 'name': name}
        self.e.upload = Mock(side_effect=prepared)
        self.e.select({'path': 'Track 1.mp3'})
        self.assertEqual(original.read_bytes(), b'original audio fixture')
        self.assertEqual(json.loads((self.e.assets/'ce5.json').read_text())['library_path'], 'Track 1.mp3')

    def test_library_rejects_path_traversal_and_escaping_symlinks(self):
        uploads = self.root/'Uploads'
        uploads.mkdir()
        outside = self.root/'private.mp3'
        outside.write_bytes(b'private')
        (uploads/'escape.mp3').symlink_to(outside)
        self.assertEqual(self.e.library(), [])
        with self.assertRaisesRegex(ValueError, 'listed in the SSD library'):
            self.e.select({'path': '../private.mp3'})

    def test_silent_schedule_starts_without_speaker_or_tone(self):
        self.e.enable({})
        self.e.tick()
        self.e.validate_output.assert_not_called()
        self.assertEqual(self.station.start.call_args.args[0]['minutes'], 3)
        self.assertFalse(self.e.auto['ce5_enabled'])

    def completed(self, condition='silence', stopped=1180):
        m = self.manifest(condition)
        m['stopped_epoch'] = stopped
        path = self.data/m['id']
        path.mkdir(exist_ok=True)
        self.e.before_finalize(m, 'Automatic stop: duration reached')
        m['frames']['state'] = 'completed'
        save(path/'manifest.json', m)
        return m

    def test_ten_minute_gap_is_measured_from_recording_stop(self):
        with patch('experiments.time.time', return_value=1000):
            self.enable(duration_minutes=3, gap_minutes=10)
            self.e.tick()
        self.completed(stopped=1180)
        with patch('experiments.time.time', return_value=1779):
            self.e.tick()
            self.assertEqual(self.station.start.call_count, 1)
            self.assertEqual(self.e.auto['phase'], 'waiting_gap')
        with patch('experiments.time.time', return_value=1780):
            self.e.tick()
            self.assertEqual(self.station.start.call_args.args[0]['condition'], 'ce5')
            self.assertEqual(self.station.start.call_args.args[0]['minutes'], 3)

    def test_hourly_silent_schedule_does_not_run_continuously(self):
        with patch('experiments.time.time', return_value=1000):
            self.e.enable({})
            self.e.tick()
        self.completed(stopped=1180)
        with patch('experiments.time.time', return_value=4599):
            self.e.tick()
            self.assertEqual(self.station.start.call_count, 1)
        with patch('experiments.time.time', return_value=4600):
            self.e.tick()
            self.assertEqual(self.station.start.call_count, 2)
            self.assertEqual(self.e.auto['next_cycle_epoch'], 8200)

    def test_schedule_rejects_overlapping_pairs(self):
        with self.assertRaisesRegex(ValueError, 'at least 26 minutes'):
            self.enable(duration_minutes=3, gap_minutes=10, interval_minutes=20)
        self.assertFalse(self.e.auto['enabled'])

    def test_settings_changes_apply_to_next_cycle(self):
        with patch('experiments.time.time', return_value=1000):
            self.enable(duration_minutes=3, gap_minutes=10)
            self.e.tick()
            self.e.configure({'duration_minutes': 5, 'gap_minutes': 1, 'frame_fps': 2})
        self.assertEqual(self.e.auto['duration_minutes'], 5)
        self.assertEqual(self.e.auto['cycle_settings']['duration_minutes'], 3)
        self.completed(stopped=1180)
        self.assertEqual(self.e.auto['next_session_epoch'], 1780)
        with patch('experiments.time.time', return_value=1780):
            self.e.tick()
        self.assertEqual(self.station.start.call_args.args[0]['minutes'], 3)

    def test_shutdown_preserves_enabled_schedule(self):
        self.e.enable({})
        m = self.manifest()
        self.e.before_finalize(m, 'Station shutting down')
        self.assertTrue(self.e.auto['enabled'])
        self.assertTrue(json.loads(self.e.config.read_text())['enabled'])
        self.assertFalse(m['trial_valid'])

    def test_restart_restores_schedule_without_replaying_interrupted_pair(self):
        save(self.e.config, dict(enabled=True, duration_minutes=3, gap_minutes=10,
             interval_minutes=60, frame_fps=2, frame_export_mode="sampled", video_fps=60, next_cycle_epoch=4600, ce5_enabled=False))
        with patch('experiments.threading.Thread'), patch('experiments.time.time', return_value=2000):
            resumed = Experiments(self.station, self.root, self.data, self.run, 'ffmpeg', {},
                                  lambda: dict(available=True, free=10*1024**3),readrate=0)
        self.assertTrue(resumed.auto['enabled'])
        self.assertEqual(resumed.auto['next_cycle_epoch'], 4600)
        self.assertEqual(resumed.auto['next_condition'], 'silence')
        self.assertIsNone(resumed.auto['last_session'])
        self.assertEqual(resumed.auto['frame_fps'], 2)

    def test_frame_export_uses_configured_rate_and_timestamps(self):
        import subprocess
        import server
        folder = self.data/'20261026T000000Z-abcdef'
        folder.mkdir()
        subprocess.run([server.FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostdin',
                        '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=30', '-t', '3',
                        '-c:v', 'libx264', '-threads', '1', str(folder/'video.mp4')],
                       env=server.ENV, check=True)
        save(folder/'manifest.json', dict(id=folder.name, state='completed', frames=dict(state='queued', fps=2)))
        self.e.ffmpeg, self.e.env = server.FFMPEG, server.ENV
        self.e.queue_frames(folder.name)
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            manifest = json.loads((folder/'manifest.json').read_text())
            if manifest['frames']['state'] in ('completed', 'failed'):
                break
            time.sleep(0.1)
        self.assertEqual(manifest['frames']['state'], 'completed', manifest)
        self.assertEqual(manifest['frames']['count'], 6)
        index = json.loads((folder/'frames/index.json').read_text())
        self.assertEqual([f['video_time_seconds'] for f in index['frames']], [0,0.5,1,1.5,2,2.5])

    def test_native_sixty_fps_export_preserves_all_frames(self):
        import hashlib
        import subprocess
        import server
        folder = self.data/'20261026T000000Z-abcdef'
        folder.mkdir()
        subprocess.run([server.FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostdin',
                        '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=60', '-frames:v', '60',
                        '-c:v', 'mjpeg', '-q:v', '2', '-threads', '1', str(folder/'video.mkv')],
                       env=server.ENV, check=True)
        save(folder/'manifest.json', dict(id=folder.name, state='completed', video_fps=60,
             frame_export_mode='all', capture_stats={'frame':60}, frames=dict(state='queued', fps=60, mode='all')))
        self.e.ffmpeg, self.e.env = server.FFMPEG, server.ENV
        self.e.queue_frames(folder.name)
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            manifest = json.loads((folder/'manifest.json').read_text())
            if manifest['frames']['state'] in ('completed','failed'):
                break
            time.sleep(0.1)
        self.assertEqual(manifest['frames']['state'], 'completed', manifest)
        self.assertEqual(manifest['frames']['count'], 60)
        self.assertEqual(manifest['video_playback']['frame_count'], 60)
        self.assertTrue(manifest['frame_integrity']['every_recorded_frame'])
        index = json.loads((folder/'frames/index.json').read_text())
        self.assertTrue(index['packet_copy'])
        for frame in index['frames']:
            self.assertEqual(hashlib.sha256((folder/'frames'/frame['file']).read_bytes()).hexdigest(), frame['sha256'])

    def test_priority_capture_can_suspend_and_resume_export_process(self):
        import subprocess
        proc=subprocess.Popen(['sleep','10'])
        stop=threading.Event()
        self.e.processing='fixture'
        self.e.processing_proc=proc
        def cooperate():
            while not stop.is_set():
                self.e.io_gate(proc)
                stop.wait(0.01)
        thread=threading.Thread(target=cooperate)
        thread.start()
        try:
            self.assertTrue(self.e.pause_exports())
            state=Path(f'/proc/{proc.pid}/status').read_text()
            self.assertIn('T',next(line for line in state.splitlines() if line.startswith('State:')))
            self.e.resume_exports()
            time.sleep(0.05)
            state=Path(f'/proc/{proc.pid}/status').read_text()
            self.assertNotIn('T',next(line for line in state.splitlines() if line.startswith('State:')))
        finally:
            stop.set()
            self.e.resume_exports()
            thread.join(timeout=2)
            proc.terminate()
            proc.wait(timeout=2)
            self.e.processing=None
            self.e.processing_proc=None

    def test_rf_extension_does_not_treat_completed_tones_as_early_failure(self):
        self.enable()
        m=self.manifest('ce5')
        m.update(started_monotonic=time.monotonic()-200,duration_limit_seconds=300,
                 playback={'state':'playing','requested_duration_seconds':180})
        self.station.active=m
        self.e.audio=Mock()
        self.e.audio.poll.return_value=0
        self.e.audio.returncode=0
        self.e.audio_log=Mock()
        self.e.tick()
        self.station.stop.assert_not_called()
        self.assertEqual(m['playback']['state'],'completed')


if __name__ == '__main__':
    unittest.main()


class RecoveryTests(unittest.TestCase):
    setUp=ExperimentTests.setUp
    tearDown=ExperimentTests.tearDown
    add_tone=ExperimentTests.add_tone
    enable=ExperimentTests.enable
    def test_temporary_rf_failure_keeps_schedule_enabled(self):
        self.enable(ce5_enabled=False)
        self.e.require_rf.side_effect=ValueError('RF unavailable')
        self.e.tick()
        self.assertTrue(self.e.auto['enabled'])
        self.assertEqual(self.e.auto['phase'],'waiting_resources')
        self.station.start.assert_not_called()
        self.e.require_rf.side_effect=None
        self.e.tick()
        self.station.start.assert_called_once()
    def test_missing_ssd_waits_without_disabling_schedule(self):
        self.enable(ce5_enabled=False)
        self.e.storage=lambda:dict(available=False,free=0)
        self.e.tick()
        self.assertTrue(self.e.auto['enabled'])
        self.assertEqual(self.e.auto['phase'],'waiting_resources')
        self.station.start.assert_not_called()
    def test_late_mount_requeues_exports(self):
        folder=self.data/'20261026T000000Z-abcdef';folder.mkdir()
        save(folder/'manifest.json',dict(id=folder.name,state='completed',frames=dict(state='queued')))
        save(folder/'buffer-state.json',dict(segments=[dict(bytes=10)]))
        self.e.queue_frames=Mock()
        self.e.storage=lambda:dict(available=False)
        self.e.resume_pending();self.e.queue_frames.assert_not_called()
        self.e.storage=lambda:dict(available=True)
        self.e.resume_pending();self.e.queue_frames.assert_called_once_with(folder.name)

    def test_truncated_native_archive_recovers_available_frames(self):
        import subprocess
        import server
        folder=self.data/'20261026T000000Z-abcdef';folder.mkdir()
        source=folder/'video.mkv'
        subprocess.run([server.FFMPEG,'-hide_banner','-loglevel','error','-nostdin',
            '-f','lavfi','-i','testsrc2=size=160x90:rate=60','-frames:v','60',
            '-c:v','mjpeg','-q:v','2','-threads','1',str(source)],env=server.ENV,check=True)
        truncated=source.read_bytes()[:int(source.stat().st_size*.75)]
        source.write_bytes(truncated)
        save(folder/'manifest.json',dict(id=folder.name,state='recording',video_fps=60,
            frame_fps=60,frame_export_mode='all',capture_stats=dict(frame=60)))
        station=server.Station.__new__(server.Station)
        with patch.object(server,'DATA',self.data),patch.object(server,'storage_status',return_value=dict(available=True)):
            station.recover_sessions()
        self.e.ffmpeg,self.e.env=server.FFMPEG,server.ENV
        self.e.resume_pending()
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            m=load(folder/'manifest.json')
            if m['frames']['state'] in ('completed','failed'):break
            time.sleep(.1)
        self.assertEqual(m['frames']['state'],'completed',m)
        self.assertGreater(m['frames']['count'],0)
        self.assertLess(m['frames']['count'],60)
        self.assertEqual(m['state'],'interrupted')
        self.assertFalse(m['trial_valid'])
        self.assertEqual(source.read_bytes(),truncated)
