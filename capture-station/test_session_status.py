"""Recording status remains responsive while disk work is blocked."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import server


class SessionStatusTests(unittest.TestCase):
    def station(self):
        station = server.Station.__new__(server.Station)
        station.lock = threading.RLock()
        station.active = dict(id='manual-one', state='recording', capture_origin='manual', rf_records=7)
        station.camera_error = None
        station.motion_trigger = SimpleNamespace(config={'enabled': True})
        station.rf_trigger = SimpleNamespace(config={'enabled': False})
        station.experiments = SimpleNamespace(auto={'enabled': False})
        return station

    def test_session_status_does_not_wait_for_capture_lock(self):
        station = self.station()
        results = []
        with station.lock:
            worker = threading.Thread(target=lambda: results.append(station.session_status()), daemon=True)
            worker.start()
            worker.join(.5)
            responsive = not worker.is_alive()
        worker.join(1)
        self.assertTrue(responsive, 'status waited behind capture disk work')
        self.assertEqual(results[0]['active']['id'], 'manual-one')
        station.active['rf_records'] = 8
        self.assertEqual(results[0]['active']['rf_records'], 7)
        station.active = None
        self.assertIsNone(station.session_status()['active'])

    def test_catalog_scan_does_not_hold_recording_control_lock(self):
        station = self.station()
        entered, release = threading.Event(), threading.Event()
        class Catalog:
            def glob(self, pattern):
                entered.set()
                release.wait(2)
                raise OSError('simulated unavailable SSD')
        def request():
            try: station.status()
            except OSError: pass
        with patch.object(server, 'DATA', Catalog()):
            worker = threading.Thread(target=request, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                acquired = station.lock.acquire(timeout=.2)
                if acquired: station.lock.release()
                self.assertTrue(acquired, 'catalog scan blocked recording controls')
                self.assertEqual(station.session_status()['active']['id'], 'manual-one')
            finally:
                release.set()
                worker.join(2)

if __name__ == '__main__': unittest.main()
