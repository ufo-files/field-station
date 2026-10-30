from collections import defaultdict
from unittest import TestCase
from training_data import session_splits
from train_camera_worker import metrics,calibration_thresholds
from object_analysis import decide_object

class TrainingTests(TestCase):
    def test_training_signature_changes_for_labels_not_notes(self):
        import tempfile,json
        from pathlib import Path
        from training_data import review_inventory
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'reviews').mkdir();(root/'images').mkdir();(root/'images/frame.jpg').write_bytes(b'fixture')
            record=dict(key='frame',training_ready=True,clean_image=True,image='frame.jpg',image_sha256='same',session_id='session',
                        human_review=dict(source_frame='after',reviewed_at='one',note='first',regions=[dict(bounds=dict(left=10,top=10,right=20,bottom=20),object='bird',shape='irregular')]))
            p=root/'reviews/frame.json';p.write_text(json.dumps(record));first=review_inventory(root)['records']['frame']['signature']
            record['human_review'].update(note='new note',reviewed_at='two');p.write_text(json.dumps(record))
            self.assertEqual(review_inventory(root)['records']['frame']['signature'],first)
            record['human_review']['regions'][0]['object']='airplane';p.write_text(json.dumps(record))
            self.assertNotEqual(review_inventory(root)['records']['frame']['signature'],first)

    def test_sessions_never_cross_splits_and_are_stable(self):
        groups={f'{label}{i}':{label} for label,n in [('bird',20),('airplane',8),('cloud',6)] for i in range(n)}
        assigned=session_splits(groups)
        for label in ('bird','airplane','cloud'):
            for role in ('train','calibration','test'):
                self.assertGreaterEqual(sum(assigned[sid]==role for sid,labels in groups.items() if label in labels),2)
        self.assertEqual(session_splits(groups,assigned),assigned)
    def test_too_few_recordings_are_not_silently_leaked(self):
        with self.assertRaises(ValueError):session_splits({str(i):{'airplane'} for i in range(3)})
    def test_calibration_requires_independent_correct_examples(self):
        rows=[dict(label='airplane',session_id='one'),dict(label='airplane',session_id='two'),dict(label='bird',session_id='three')]
        predictions=[dict(identifier='airplane',confidence=.95),dict(identifier='airplane',confidence=.96),dict(identifier='bird',confidence=.9)]
        policy=calibration_thresholds(rows,predictions,['airplane','bird'])
        self.assertLessEqual(policy['airplane'],.95);self.assertGreater(policy['bird'],1)
        rows[1]['session_id']='one'
        self.assertGreater(calibration_thresholds(rows,predictions,['airplane'])['airplane'],1)
    def test_cloud_suppression_mistakes_are_measured(self):
        result=metrics(['bird','airplane','cloud'],['cloud','airplane','bird'])
        self.assertEqual(result['cloud_false_suppression'],1)
        self.assertEqual(result['bird']['fp'],1)
    def test_validated_custom_model_can_label_sub16_pixel_targets(self):
        value=dict(identifier='bird',confidence=.95,source='camera-trained',threshold=.9,minimum_native_size=8,model_version='test')
        self.assertEqual(decide_object([[value]],10,0)['label'],'bird')
        self.assertEqual(decide_object([[value]],7,0)['label'],'unknown')
        value['confidence']=.8
        self.assertEqual(decide_object([[value]],10,0)['label'],'unknown')
        value['confidence']=.99
        self.assertEqual(decide_object([[],[value]],10,0)['label'],'unknown')
