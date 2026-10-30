import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock
from types import SimpleNamespace
import threading
import numpy as np
from PIL import Image,ImageDraw
from object_analysis import shape_measurement,decide_object,ObjectAnalysis
from boxed_frames import sync_boxed

class AnalysisTests(TestCase):
    def test_shape_single_frame_circle_elongation_and_small(self):
        im=Image.new('L',(160,160),50);ImageDraw.Draw(im).ellipse((50,50,90,90),fill=220)
        circle=shape_measurement(im,dict(left=48,top=48,right=93,bottom=93))
        self.assertEqual(circle['label'],'round',circle)
        im=Image.new('L',(160,160),50);ImageDraw.Draw(im).ellipse((30,65,120,78),fill=220)
        long=shape_measurement(im,dict(left=28,top=63,right=123,bottom=81))
        self.assertEqual(long['label'],'elongated',long)
        im=Image.new('L',(80,80),50);ImageDraw.Draw(im).ellipse((30,30,34,34),fill=220)
        self.assertEqual(shape_measurement(im,dict(left=28,top=28,right=37,bottom=37))['label'],'too_small')
    def test_no_detail_is_unresolved(self):
        self.assertEqual(shape_measurement(Image.new('L',(100,100),50),dict(left=20,top=20,right=60,bottom=60))['label'],'unresolved')
    def test_object_requires_native_detail_and_two_consistent_frames(self):
        bird=[dict(identifier='bird',confidence=.95)]
        plane=[dict(identifier='airplane',confidence=.96)]
        self.assertEqual(decide_object([bird,bird],30)['label'],'bird')
        self.assertEqual(decide_object([plane,plane],30)['label'],'airplane')
        self.assertEqual(decide_object([bird,plane],30)['label'],'unknown')
        self.assertEqual(decide_object([bird,bird],7)['label'],'unknown')
        self.assertEqual(decide_object([bird],30)['label'],'unknown')
        self.assertEqual(decide_object([[dict(identifier='bird',confidence=.99)]],40)['label'],'bird')
        self.assertEqual(decide_object([[dict(identifier='sky',confidence=.999)]]*2,30)['label'],'unknown')
    def test_classified_copies_update_and_survive_original_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sid='20261028T010000Z-abcdef';eid='0123456789abcdef';folder=root/sid;folder.mkdir()
            name=f'motion-{eid}-boxed.jpg';(folder/name).write_bytes(b'boxed image')
            def events(label):
                (folder/'motion-events.json').write_text(json.dumps([dict(id=eid,classification=dict(state='completed',regions=[dict(object=dict(label=label),shape=dict(label='round'))]))]))
            events('bird');sync_boxed(root)
            base=root/'boxed-frames'/'classified';filename=sid+'--'+name
            self.assertTrue((base/'objects'/'bird'/filename).exists())
            self.assertTrue((base/'shapes'/'round'/filename).exists())
            events('airplane');sync_boxed(root)
            self.assertFalse((base/'objects'/'bird'/filename).exists())
            self.assertTrue((base/'objects'/'airplane'/filename).exists())
            (folder/name).unlink();(folder/'motion-events.json').unlink();sync_boxed(root)
            self.assertTrue((base/'objects'/'airplane'/filename).exists())
    def test_box_label_matches_region_without_borrowing_unrelated_label(self):
        from classification_labels import label_text,matching_region
        box=dict(left=10,top=10,right=40,bottom=40)
        region=dict(bounds=box,object=dict(label='bird'),shape=dict(label='elongated'))
        self.assertEqual(label_text(matching_region(box,[region])),'Likely bird | elongated')
        self.assertIsNone(matching_region(dict(left=100,top=100,right=130,bottom=130),[region]))

    def test_live_labels_expire_and_do_not_identify_distant_regions(self):
        import time
        analyzer=ObjectAnalysis.__new__(ObjectAnalysis)
        box=dict(left=10,top=10,right=40,bottom=40)
        region=dict(bounds=box,object=dict(label='bird'),shape=dict(label='elongated'))
        analyzer.live_result=dict(detected_epoch=time.time(),regions=[region])
        data=dict(width=1920,height=1080,boxes=[box])
        self.assertEqual(analyzer.decorate_overlay(data)['boxes'][0]['label'],'Likely bird | elongated')
        analyzer.live_result['detected_epoch']-=10
        self.assertEqual(analyzer.decorate_overlay(data)['boxes'][0]['label'],'Motion | analyzing')

    def test_known_cloud_is_not_boxed_on_live_preview(self):
        import time
        analyzer=ObjectAnalysis.__new__(ObjectAnalysis)
        box=dict(left=10,top=10,right=40,bottom=40)
        cloud=dict(bounds=box,object=dict(label='cloud',source='human'),shape=dict(label='unresolved'))
        analyzer.live_result=dict(detected_epoch=time.time(),regions=[cloud])
        data=dict(width=1920,height=1080,boxes=[box,dict(left=100,top=100,right=130,bottom=130)],manual_target=box)
        result=analyzer.decorate_overlay(data)
        self.assertEqual(len(result['boxes']),1)
        self.assertEqual(result['boxes'][0]['left'],100)
        self.assertIsNone(result['manual_target'])

    def test_analysis_model_failure_retains_shape_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);eid='0123456789abcdef';im=Image.new('RGB',(120,120),(40,40,40));ImageDraw.Draw(im).ellipse((45,45,75,75),fill='white')
            for suffix in ('before','after'):im.save(p/f'motion-{eid}-{suffix}.jpg')
            analyzer=ObjectAnalysis.__new__(ObjectAnalysis);analyzer.remote=Mock(side_effect=OSError('offline'))
            result=analyzer.analyze(p,dict(id=eid,annotation=dict(boxes=[dict(left=43,top=43,right=78,bottom=78)])))
            self.assertEqual(result['mode'],'label_only');self.assertEqual(result['regions'][0]['shape']['label'],'round')
            self.assertEqual(result['regions'][0]['object']['label'],'unknown');self.assertEqual(result['error'],'offline')
