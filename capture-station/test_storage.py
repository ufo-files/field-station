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
