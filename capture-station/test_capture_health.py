import json,tempfile,unittest
from pathlib import Path
from capture_health import CaptureHealth

class CaptureHealthTests(unittest.TestCase):
    def test_counts_native_timestamps_gaps_and_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            health=CaptureHealth(Path(folder))
            health.feed('config in time_base: 1/1000000, frame_rate: 0/1')
            for i,pts in enumerate([0,16683,33367,66733]):
                health.feed(f'n: {i} pts: {pts} pts_time:{pts/1000000}')
            health.feed('UFO_AVF_OVERWRITE total=1')
            status=health.snapshot();health.close()
            self.assertEqual(status['captured_frames'],4)
            self.assertEqual(status['inferred_missing_frames'],1)
            self.assertEqual(status['timestamp_gap_count'],1)
            self.assertEqual(status['overwritten_frames'],1)
            self.assertLess(status['measured_fps'],50)
            frames=[json.loads(line) for line in (Path(folder)/'frame-times-000000000.jsonl').read_text().splitlines()]
            self.assertEqual([row['pts'] for row in frames],[0,16683,33367,66733])
    def test_duplicate_timestamp_is_flagged_not_accepted_as_healthy(self):
        with tempfile.TemporaryDirectory() as folder:
            health=CaptureHealth(Path(folder))
            for i in range(2):health.feed(f'n: {i} pts: 0 pts_time:0')
            self.assertEqual(health.snapshot()['nonmonotonic_timestamps'],1)
            health.close()
