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

    def test_camera_waits_for_space_then_retries_without_killing_monitor(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        station=server.Station.__new__(server.Station)
        station.experiments=SimpleNamespace(storage_reserve=lambda:300,auto={'video_fps':60})
        station.active=None;station.buffer=SimpleNamespace(new_run=Mock(side_effect=RuntimeError('camera start reached')))
        with patch.object(server,'storage_status',return_value=dict(available=True,free=100)):
            self.assertFalse(station.spawn_camera())
            self.assertIn('storage reserve',station.camera_error)
            station.buffer.new_run.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'RUN',Path(tmp)),patch.object(server,'storage_status',return_value=dict(available=True,free=1000)):
            with self.assertRaisesRegex(RuntimeError,'camera start reached'):station.spawn_camera()
            station.log.close()
            self.assertIsNone(station.camera_error)

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


if __name__ == '__main__':
    unittest.main()
