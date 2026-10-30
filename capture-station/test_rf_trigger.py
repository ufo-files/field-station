import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from rf_trigger import RFTrigger


class RFTriggerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = 100000.0
        self.clock_patch = patch('rf_trigger.time.time',lambda:self.clock)
        self.clock_patch.start()
        self.station = SimpleNamespace(lock=threading.RLock(),active=None,
            experiments=SimpleNamespace(pause_exports=Mock(return_value=True),resume_exports=Mock()),
            start=Mock(return_value={'id':'test-session'}),data_path=lambda sid:self.root/sid)
        self.trigger = RFTrigger(self.station,self.root)
        self.trigger.configure(dict(enabled=True,baseline_samples=10,baseline_window=30,cooldown_minutes=0))

    def tearDown(self):
        self.clock_patch.stop()
        self.temp.cleanup()

    def frame(self,peak=None,floor=-70,shift=0):
        values=[-70+shift]*200
        if peak is not None:
            values[peak]=-45+shift
        return dict(timestamp=self.clock,range_hz=[1590000000,1610000000],bin_width_hz=100000,
                    noise_floor_db=floor,maximum_db=values)

    def feed(self,peak=None,floor=-70,shift=0):
        self.clock+=1
        frame=self.frame(peak,floor,shift)
        self.trigger.tick(frame)
        return frame

    def warm(self,peak=None):
        for _ in range(10):
            self.feed(peak)

    def test_learns_before_arming(self):
        for _ in range(9):self.feed(80)
        self.assertEqual(self.trigger.phase,'learning_baseline')
        self.station.start.assert_not_called()

    def test_stable_strong_carrier_does_not_trigger(self):
        self.warm(80)
        for _ in range(10):self.feed(80)
        self.assertGreater(self.trigger.peak,20)
        self.station.start.assert_not_called()

    def test_two_fresh_novel_peaks_trigger_three_minutes(self):
        self.warm()
        self.feed(80)
        self.station.start.assert_not_called()
        self.feed(80)
        body=self.station.start.call_args.args[0]
        self.assertEqual(body['minutes'],3)
        event=self.station.start.call_args.kwargs['trigger_event']
        self.assertEqual(event['detection']['kind'],'new_peak')
        self.assertEqual(event['detection']['baseline_rise_db'],25)
        self.assertEqual(len(event['detection']['baseline_bin_db']),200)
        self.station.experiments.pause_exports.assert_called_once()

    def test_duplicate_snapshot_is_not_second_confirmation(self):
        self.warm()
        frame=self.feed(80)
        self.trigger.tick(frame)
        self.station.start.assert_not_called()

    def test_stale_or_wrong_band_snapshot_is_rejected(self):
        self.warm()
        frame=self.frame(80)
        frame['timestamp']-=10
        self.trigger.tick(frame)
        self.assertEqual(self.trigger.phase,'waiting_for_fresh_rf')
        frame['timestamp']=self.clock
        frame['range_hz']=[1600000000,1620000000]
        self.trigger.tick(frame)
        self.station.start.assert_not_called()

    def test_carrier_must_confirm_in_same_frequency_region(self):
        self.warm()
        self.feed(80)
        self.feed(110)
        self.station.start.assert_not_called()
        self.feed(110)
        self.station.start.assert_called_once()

    def test_broadband_floor_rise_is_detected_without_peak_snr(self):
        self.warm()
        self.feed(floor=-60,shift=10)
        self.feed(floor=-60,shift=10)
        event=self.station.start.call_args.kwargs['trigger_event']
        self.assertEqual(event['detection']['kind'],'broadband_rise')
        self.assertEqual(event['detection']['above_floor_db'],0)
        self.assertEqual(event['detection']['baseline_rise_db'],10)

    def test_normal_broadband_fluctuation_does_not_trigger(self):
        self.warm()
        for _ in range(5):self.feed(floor=-66,shift=4)
        self.station.start.assert_not_called()

    def test_one_persistent_signal_does_not_start_repeat_recordings(self):
        self.warm()
        for _ in range(20):self.feed(80)
        self.station.start.assert_called_once()

    def test_rearms_after_quiet(self):
        self.warm()
        self.feed(80);self.feed(80)
        for _ in range(3):self.feed()
        self.feed(80);self.feed(80)
        self.assertEqual(self.station.start.call_count,2)

    def test_busy_capture_is_pending_and_retried(self):
        self.warm()
        self.station.experiments.pause_exports.return_value=False
        self.feed(80);self.feed(80)
        self.assertIsNotNone(self.trigger.pending)
        self.station.start.assert_not_called()
        self.station.experiments.pause_exports.return_value=True
        self.feed()
        self.station.start.assert_called_once()

    def test_overdue_pending_event_is_reported_as_missed(self):
        self.warm()
        self.station.experiments.pause_exports.return_value=False
        self.feed(80);self.feed(80)
        self.clock+=31
        self.feed()
        self.assertIsNone(self.trigger.pending)
        self.assertEqual(self.trigger.last_event['action'],'missed_capture')
        self.station.start.assert_not_called()

    def test_existing_recording_is_extended_with_event_evidence(self):
        self.warm()
        folder=self.root/'active'
        folder.mkdir()
        self.station.active=dict(id='active',started_monotonic=time.monotonic()-120,
                                  duration_limit_seconds=180,markers=[])
        self.feed(80);self.feed(80)
        self.assertGreaterEqual(self.station.active['duration_limit_seconds'],300)
        self.assertEqual(len(self.station.active['markers']),1)
        self.assertTrue((folder/'rf-trigger-events.json').exists())
        self.station.start.assert_not_called()

    def test_long_data_gap_resets_baseline(self):
        self.warm()
        self.clock+=10
        self.feed()
        self.assertEqual(len(self.trigger.history),1)
        self.assertEqual(self.trigger.phase,'learning_baseline')

    def test_confirmation_evidence_retains_both_observed_snapshots(self):
        self.warm()
        first=self.feed(80)
        second=self.feed(80)
        event=self.station.start.call_args.kwargs['trigger_event']
        self.assertEqual([f['timestamp'] for f in event['confirmation_spectra']], [first['timestamp'],second['timestamp']])


if __name__=='__main__':
    unittest.main()
