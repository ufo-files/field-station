import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from unittest import TestCase
import zipfile
from PIL import Image,ImageDraw
from boxed_review import BoxedReview
from object_analysis import ObjectAnalysis
from classification_labels import effective_classification
from experiments import save,load

class BoxedReviewTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'sessions';self.data.mkdir()
        self.sid='20261028T010000Z-abcdef';self.eid='0123456789abcdef';self.key=self.sid+'--motion-'+self.eid+'-boxed.jpg'
        self.folder=self.data/self.sid;self.folder.mkdir();(self.data/'boxed-frames').mkdir()
        im=Image.new('RGB',(120,100),(40,40,40));ImageDraw.Draw(im).ellipse((40,40,60,60),fill='white')
        for suffix in ('before','after','boxed'):im.save(self.folder/f'motion-{self.eid}-{suffix}.jpg')
        im.save(self.data/'boxed-frames'/self.key)
        self.box=dict(left=38,top=38,right=63,bottom=63)
        self.event=dict(id=self.eid,settings=dict(pixel_threshold=12),annotation=dict(source_frame='after',boxes=[self.box]),classification=dict(state='completed',regions=[dict(bounds=self.box,source_frame='after',object=dict(label='unknown'),shape=dict(label='round'))]))
        save(self.folder/'motion-events.json',[self.event]);save(self.folder/'manifest.json',dict(id=self.sid,motion_events=[self.event],files={}))
        self.station=SimpleNamespace(lock=threading.RLock(),active=None,data_path=lambda sid:self.data/sid,motion_trigger=SimpleNamespace(last_event=None))
        self.review=BoxedReview(self.station,self.data);self.station.boxed_review=self.review
    def tearDown(self):self.tmp.cleanup()
    def body(self):return dict(key=self.key,regions=[dict(bounds=self.box,object='bird',shape='round')],boxes_confirmed=True,note='Observer correction')
    def test_all_frames_list_and_search(self):
        self.assertEqual(self.review.listing({})['total'],1)
        self.assertEqual(self.review.listing({'search':[self.eid]})['items'][0]['key'],self.key)
        self.assertEqual(self.review.detail(self.key)['regions'][0]['object'],'unknown')
    def test_save_overrides_display_not_prediction_and_retains_clean_training_image(self):
        result=self.review.save_review(self.body());self.assertTrue(result['training_ready'])
        event=load(self.folder/'motion-events.json')[0]
        self.assertEqual(event['classification']['regions'][0]['object']['label'],'unknown')
        self.assertEqual(effective_classification(event)['regions'][0]['object']['label'],'bird')
        self.assertIn('Bird (reviewed)',event['annotation']['boxes'][0]['label'])
        self.assertEqual(self.review.image(self.key,True).read_bytes(),(self.folder/f'motion-{self.eid}-after.jpg').read_bytes())
        index=load(self.data/'boxed-frames/classification-index.json');self.assertEqual(index[self.key]['objects'],['bird'])
        self.assertTrue(self.review.listing({'review':['training_ready']})['items'][0]['reviewed'])
        (self.folder/f'motion-{self.eid}-after.jpg').unlink()
        self.assertEqual(self.review.detail(self.key)['clean_image'],True)
    def test_export_contains_only_confirmed_clean_examples(self):
        body=self.body();body['boxes_confirmed']=False;self.review.save_review(body)
        with zipfile.ZipFile(io.BytesIO(self.review.export_training())) as z:self.assertFalse(any(n.startswith('images/') for n in z.namelist()))
        self.review.save_review(self.body())
        with zipfile.ZipFile(io.BytesIO(self.review.export_training())) as z:
            name=self.key[:-4]
            self.assertEqual(z.read('images/'+name+'.jpg'),(self.folder/f'motion-{self.eid}-after.jpg').read_bytes())
            self.assertTrue(z.read('labels/'+name+'.txt').decode().startswith('0 '))
            self.assertEqual(json.loads(z.read('examples.json'))[0]['session_id'],self.sid)
    def test_boxed_only_frame_can_be_corrected_but_not_used_for_training(self):
        for suffix in ('before','after'):(self.folder/f'motion-{self.eid}-{suffix}.jpg').unlink()
        self.assertFalse(self.review.detail(self.key)['clean_image'])
        result=self.review.save_review(self.body())
        self.assertFalse(result['training_ready'])
        self.assertEqual(self.review.detail(self.key)['human_review']['regions'][0]['object'],'bird')
        self.assertFalse(self.review.detail(self.key)['clean_image'])
        with zipfile.ZipFile(io.BytesIO(self.review.export_training())) as z:self.assertFalse(any(n.startswith('images/') for n in z.namelist()))

    def test_invalid_boxes_and_paths_do_not_save(self):
        body=self.body();body['regions'][0]['bounds']=dict(left=-1,top=10,right=30,bottom=20)
        with self.assertRaises(ValueError):self.review.save_review(body)
        with self.assertRaises(ValueError):self.review.detail('../../etc/passwd')
        body=self.body();body['regions'][0]['object']='not_a_class'
        with self.assertRaises(ValueError):self.review.save_review(body)
    def test_cloud_review_removes_boxes_and_exports_as_negative(self):
        body=self.body();body['regions'][0]['object']='cloud'
        result=self.review.save_review(body);self.assertTrue(result['training_ready'])
        event=load(self.folder/'motion-events.json')[0]
        self.assertEqual(event['annotation']['boxes'],[])
        self.assertEqual(event['human_review']['regions'][0]['shape'],'unresolved')
        self.assertEqual(self.review.detail(self.key)['regions'][0]['object'],'cloud')
        index=load(self.data/'boxed-frames/classification-index.json');self.assertEqual(index[self.key]['objects'],['cloud'])
        with zipfile.ZipFile(io.BytesIO(self.review.export_training())) as z:
            self.assertNotIn('cloud',json.loads(z.read('classes.json')))
            self.assertEqual(z.read('labels/'+self.key[:-4]+'.txt'),b'')

    def test_anomalous_flag_retains_boxes_and_is_not_a_training_identity(self):
        body=self.body();body['regions'][0]['object']='anomalous'
        result=self.review.save_review(body)
        self.assertFalse(result['training_ready'])
        event=load(self.folder/'motion-events.json')[0]
        self.assertEqual(len(event['annotation']['boxes']),1)
        self.assertIn('Anomalous',event['annotation']['boxes'][0]['label'])
        self.assertEqual(self.review.detail(self.key)['regions'][0]['object'],'anomalous')
        index=load(self.data/'boxed-frames/classification-index.json')
        self.assertEqual(index[self.key]['objects'],['anomalous'])
        package=self.data/'anomalous'/(self.sid+'--'+self.eid)
        self.assertTrue((package/'event.json').exists())
        self.assertTrue((package/f'motion-{self.eid}-boxed.jpg').exists())
        self.assertNotEqual((package/f'motion-{self.eid}-boxed.jpg').stat().st_ino,(self.folder/f'motion-{self.eid}-boxed.jpg').stat().st_ino)
        with zipfile.ZipFile(io.BytesIO(self.review.export_training())) as z:self.assertNotIn('anomalous',json.loads(z.read('classes.json')))

    def test_source_video_local_and_event_preview_links(self):
        manifest=load(self.folder/'manifest.json');manifest['started_epoch']=100
        event=load(self.folder/'motion-events.json')[0];event['detected_epoch']=110
        save(self.folder/'motion-events.json',[event]);save(self.folder/'manifest.json',manifest)
        (self.folder/'video.mp4').write_bytes(b'mp4')
        spec=self.review.video_info(self.key)
        self.assertEqual(spec['kind'],'full_recording');self.assertEqual(spec['event_seconds'],10)
        (self.folder/'video.mp4').unlink();(self.folder/f'review-{self.eid}.mp4').write_bytes(b'preview')
        save(self.folder/f'review-{self.eid}.json',dict(start=7,event_seconds=3))
        spec=self.review.video_info(self.key);self.assertEqual(spec['kind'],'event_preview');self.assertEqual(spec['event_seconds'],3)

    def test_saved_crop_is_native_and_smoothed_preview_is_enlarged(self):
        native=self.review.crop_image(self.key,0,True);smooth=self.review.crop_image(self.key,0,False)
        original=Image.open(self.folder/f'motion-{self.eid}-after.jpg').convert('RGB')
        crop=Image.open(native).convert('RGB');display=Image.open(smooth);display.load()
        self.assertEqual(crop.size,(73,73));self.assertEqual(display.size,(1024,1024))
        self.assertEqual(crop.tobytes(),original.crop((14,14,87,87)).tobytes())
        self.assertIn('detail_crops',self.review.detail(self.key))

    def test_negative_example_has_empty_labels(self):
        self.review.save_review(dict(key=self.key,regions=[],no_object=True,boxes_confirmed=True))
        with zipfile.ZipFile(io.BytesIO(self.review.export_training())) as z:self.assertEqual(z.read('labels/'+self.key[:-4]+'.txt'),b'')
    def test_model_recheck_cannot_overwrite_observer_correction(self):
        self.review.save_review(self.body());analyzer=ObjectAnalysis.__new__(ObjectAnalysis);analyzer.station=self.station
        result=dict(state='completed',regions=[dict(bounds=self.box,object=dict(label='airplane'),shape=dict(label='elongated'))])
        analyzer.persist(self.sid,self.eid,result)
        event=load(self.folder/'motion-events.json')[0]
        self.assertEqual(event['human_review']['regions'][0]['object'],'bird')
        self.assertEqual(event['classification']['regions'][0]['object']['label'],'airplane')
        self.assertIn('Bird (reviewed)',event['annotation']['boxes'][0]['label'])
