import unittest
from temporal_model import feature_window, fit, predict, windows

def point(i, x, y=0.2, w=.05, h=.05, source='a', track='one', label='anomalous'):
    return dict(time=i/60, frame_index=i, source_sha256=source, track_id=track,
                label=label, bounds=dict(x=x, y=y, w=w, h=h))

class TemporalTests(unittest.TestCase):
    def test_reversal_and_shape_change_are_distinct_from_straight_motion(self):
        straight=[point(0,.1),point(1,.2),point(2,.3)]
        reversal=[point(0,.1),point(1,.2),point(2,.1,w=.1)]
        a,b=feature_window(straight),feature_window(reversal)
        self.assertAlmostEqual(a[6],1)
        self.assertAlmostEqual(b[6],-1)
        self.assertNotEqual(a[11],b[11])
        self.assertNotEqual(a[13],b[13])
    def test_multiple_objects_and_sources_do_not_cross_link(self):
        records=[point(i,.1+i*.01,source=s,track=t) for s in ('a','b') for t in ('one','two') for i in range(3)]
        self.assertEqual(len(windows(records)),4)
        model=fit(records)
        self.assertEqual(model['evaluation']['state'],'leave_one_source_out')
        self.assertEqual(model['evaluation']['total'],4)
        self.assertEqual(predict(model,records[:3])['label'],'anomalous')
    def test_overlapping_clips_from_one_capture_cannot_be_independent_test_sources(self):
        rows=[dict(point(i,.1+i*.01,source=source),recording_group='capture:one') for source in ('clip-a','clip-b') for i in range(3)]
        model=fit(rows);self.assertEqual(model['source_count'],2);self.assertEqual(model['recording_group_count'],1);self.assertEqual(model['evaluation']['state'],'needs_two_independent_recordings');self.assertNotIn('accuracy',model['evaluation'])
    def test_singletons_are_not_temporal_training(self):
        self.assertEqual(fit([point(0,.1)])['state'],'needs_temporal_annotations')
        rows=[point(i,.1) for i in range(3)]
        for row in rows:row.pop('track_id')
        self.assertEqual(windows(rows),[])
    def test_time_gaps_are_preserved_and_duplicates_rejected(self):
        rows=[point(0,.1),point(1,.2),point(5,.3)]
        self.assertAlmostEqual(feature_window(rows)[15],4/60)
        with self.assertRaises(ValueError):windows([rows[0],rows[0],rows[1]])
    def test_identity_cannot_change_class_mid_track(self):
        with self.assertRaises(ValueError):windows([point(0,.1),point(1,.2,label='bird')])

if __name__=='__main__':unittest.main()
