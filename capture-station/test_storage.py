import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server


class StorageTests(unittest.TestCase):
    def test_missing_mount_is_unavailable_even_when_directory_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            volume = Path(temp)
            data = volume / 'sessions'
            data.mkdir()
            with patch.multiple(server, DATA=data, VOLUME=temp, VOLUME_ID='test'), patch.object(Path, 'is_mount', return_value=False):
                self.assertFalse(server.storage_status()['available'])
                station = server.Station.__new__(server.Station)
                station.lock = __import__('threading').RLock()
                station.active = None
                station.experiments = __import__('types').SimpleNamespace(auto={'enabled': False},readrate=0, processing=None, pending=set())
                with self.assertRaisesRegex(ValueError, 'drive unavailable'):
                    station.start({})
                self.assertEqual(list(data.iterdir()), [])

    def test_wrong_volume_marker_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            volume = Path(temp)
            (volume / '.field-station-volume').write_text('other-drive')
            with patch.multiple(server, DATA=volume, VOLUME=temp, VOLUME_ID='expected-drive'), patch.object(Path, 'is_mount', return_value=True):
                self.assertFalse(server.storage_status()['available'])

    def test_data_outside_ssd_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            volume = Path(temp) / 'volume'
            volume.mkdir()
            with patch.multiple(server, DATA=Path(temp), VOLUME=str(volume), VOLUME_ID=''), patch.object(Path, 'is_mount', return_value=True):
                self.assertFalse(server.storage_status()['available'])

    def test_correct_volume_reports_its_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            volume = Path(temp)
            (volume / '.field-station-volume').write_text('expected-drive\n')
            data = volume / 'sessions'
            data.mkdir()
            with patch.multiple(server, DATA=data, VOLUME=temp, VOLUME_ID='expected-drive'), patch.object(Path, 'is_mount', return_value=True):
                status = server.storage_status()
                self.assertTrue(status['available'])
                self.assertGreater(status['free'], 0)
                self.assertEqual(status['path'], str(data))

    def test_preview_survives_pressure_and_recording_recovers_with_headroom(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        gib=1024**3
        station=server.Station.__new__(server.Station)
        station.experiments=SimpleNamespace(storage_reserve=lambda:100*gib,auto={'video_fps':60})
        station.active=None;station.buffer=SimpleNamespace(new_run=Mock(),durable=True)
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'RUN',Path(tmp)),patch.object(server.subprocess,'Popen') as popen,patch.dict(os.environ,{'CAPTURE_FFMPEG':''}):
            station.buffer.new_run.return_value=Path(tmp)/'segments'
            for free,available,paused in [(99,True,True),(101,True,True),(0,False,True),(110,True,False)]:
                with patch.object(server,'storage_status',return_value=dict(available=available,free=free*gib)):
                    station.spawn_camera()
                args=popen.call_args.args[0]
                self.assertIn(str(server.PREVIEW),args)
                self.assertEqual('segment' in args,not paused)
                self.assertEqual(station.preview_only,paused)
                self.assertIsNone(station.camera_error)
                if paused:
                    station.buffer.new_run.assert_not_called()
                    self.assertIs(popen.call_args.kwargs['stderr'],station.log)
                station.log.close()
            station.buffer.new_run.assert_called_once()

    def test_failed_health_flush_still_closes_camera_pipe(self):
        import io
        from unittest.mock import Mock
        from capture_health import drain_camera_log
        pipe=io.BytesIO(b'');health=Mock();health.close.side_effect=FileNotFoundError('volume disconnected')
        with self.assertRaises(FileNotFoundError):drain_camera_log(pipe,io.StringIO(),health)
        self.assertTrue(pipe.closed)

    def test_disconnect_during_shutdown_leaves_camera_restartable(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        station=server.Station.__new__(server.Station)
        station.proc=Mock(returncode=1);station.proc.poll.return_value=1
        station.buffer=SimpleNamespace(durable=True,path=Path('/missing/recording'),ingest=Mock())
        station.log=Mock()
        with patch.object(server,'write_json',side_effect=FileNotFoundError('volume disconnected')):
            self.assertEqual(station.stop_camera(),1)
        self.assertIsNone(station.proc);station.log.close.assert_called_once()
        self.assertIn('volume unavailable',station.camera_error)

    def test_interrupted_archive_queued_and_never_labeled_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp);folder=data/'20261026T000000Z-abcdef';folder.mkdir()
            (folder/'video.mkv').write_bytes(b'partial archive fixture')
            server.write_json(folder/'manifest.json',dict(id=folder.name,state='recording',video_fps=60,
                frame_export_mode='all',capture_stats=dict(frame=999)))
            station=server.Station.__new__(server.Station)
            with patch.object(server,'DATA',data),patch.object(server,'storage_status',return_value=dict(available=True)):
                station.recover_sessions()
            m=server.read_json(folder/'manifest.json')
            self.assertEqual(m['state'],'interrupted')
            self.assertFalse(m['trial_valid'])
            self.assertEqual(m['frames']['state'],'queued')
            self.assertEqual(m['frames']['mode'],'all')
            self.assertNotIn('capture_stats',m)
            self.assertEqual((folder/'video.mkv').read_bytes(),b'partial archive fixture')

    def test_stalled_camera_reconnects_without_losing_the_station(self):
        from unittest.mock import Mock
        station=server.Station.__new__(server.Station)
        station.proc=Mock();station.proc.poll.return_value=None
        station.capture_health=Mock();station.capture_health.snapshot.return_value={'captured_frames':120}
        station.camera_progress=120;station.camera_progress_monotonic=100
        station.active=None;station.next_retry=0
        station.stop_camera=Mock(side_effect=lambda:setattr(station,'proc',None))
        station.spawn_camera=Mock()
        with patch.object(server.time,'monotonic',return_value=111):station.maintain_camera()
        station.stop_camera.assert_called_once();station.spawn_camera.assert_not_called()
        with patch.object(server.time,'monotonic',return_value=117):station.maintain_camera()
        station.spawn_camera.assert_called_once()

    def test_camera_progress_and_startup_grace_prevent_restart_loops(self):
        from unittest.mock import Mock
        station=server.Station.__new__(server.Station)
        station.proc=Mock();station.proc.poll.return_value=None
        station.capture_health=Mock();station.capture_health.snapshot.return_value={'captured_frames':0}
        station.camera_progress=None;station.camera_progress_monotonic=100
        station.active=None;station.next_retry=0;station.stop_camera=Mock()
        with patch.object(server.time,'monotonic',return_value=119):station.maintain_camera()
        station.stop_camera.assert_not_called()
        station.capture_health.snapshot.return_value={'captured_frames':1}
        with patch.object(server.time,'monotonic',return_value=121):station.maintain_camera()
        self.assertEqual(station.camera_progress_monotonic,121)
        with patch.object(server.time,'monotonic',return_value=129):station.maintain_camera()
        station.stop_camera.assert_not_called()

    def test_disconnected_camera_retries_until_device_returns(self):
        from unittest.mock import Mock
        station=server.Station.__new__(server.Station)
        dead=Mock();dead.poll.return_value=1;station.proc=dead
        station.active=None;station.next_retry=0
        station.stop_camera=Mock(side_effect=lambda:setattr(station,'proc',None))
        station.spawn_camera=Mock(side_effect=lambda:setattr(station,'proc',dead))
        with patch.object(server.time,'monotonic',return_value=100):station.maintain_camera()
        with patch.object(server.time,'monotonic',return_value=106):station.maintain_camera()
        with patch.object(server.time,'monotonic',return_value=107):station.maintain_camera()
        with patch.object(server.time,'monotonic',return_value=113):station.maintain_camera()
        self.assertEqual(station.spawn_camera.call_count,2)
        self.assertEqual(station.stop_camera.call_count,2)


if __name__ == '__main__':
    unittest.main()

class StorageRecoveryTests(unittest.TestCase):
    def test_pause_persists_until_headroom_recovers(self):
        from storage_recovery import update_pause
        gib=1024**3;reserve=100*gib
        state=update_pause(dict(available=True,free=99*gib),reserve)
        self.assertTrue(state['paused'])
        self.assertTrue(update_pause(dict(available=True,free=101*gib),reserve,state)['paused'])
        recovered=update_pause(dict(available=True,free=110*gib),reserve,state)
        self.assertFalse(recovered['paused'])
        self.assertFalse(update_pause(dict(available=True,free=105*gib),reserve,recovered)['paused'])
    def test_disconnect_does_not_clear_recovery_state(self):
        from storage_recovery import update_pause
        self.assertTrue(update_pause(dict(available=False,free=0),100*1024**3,dict(paused=True))['paused'])
