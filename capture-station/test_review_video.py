from unittest import TestCase
from review_video import event_position,clip_window

class ReviewVideoTests(TestCase):
    def test_event_position_accounts_for_comparison_source(self):
        event=dict(detected_epoch=115,settings=dict(reference_seconds=.8))
        self.assertEqual(event_position(dict(started_epoch=100),event),15)
        self.assertAlmostEqual(event_position(dict(started_epoch=100),event,'before'),14.2)
    def test_clip_keeps_event_inside_short_or_end_of_recording(self):
        for pos,duration in ((10,30),(29,30),(0,4),(100,20)):
            clip=clip_window(pos,duration)
            self.assertGreater(clip['duration'],0);self.assertLessEqual(clip['start']+clip['duration'],duration)
            self.assertLessEqual(clip['event_seconds'],clip['duration'])
