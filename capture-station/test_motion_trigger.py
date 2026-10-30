import json
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np
from PIL import Image
from motion_trigger import MotionTrigger, motion_array, motion_score, changed_regions, annotate_motion, validate_polygon, region_geometry

class MotionTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.station=SimpleNamespace(lock=threading.RLock(),exiting=threading.Event(),active=None,
            experiments=SimpleNamespace(pause_exports=Mock(return_value=True),resume_exports=Mock()),
            data_path=lambda sid:self.root/sid)
        self.annotator=patch('motion_trigger.annotate_motion',return_value={'boxes':[]})
        self.annotator.start()
        self.addCleanup(self.annotator.stop)
        self.trigger=MotionTrigger(self.station,self.root,self.root/'preview.jpg')
    def tearDown(self):
        self.station.exiting.set()
        self.trigger.worker.join(2)
        self.tmp.cleanup()
    def test_cloud_filter_rejects_diffuse_shift_and_preserves_compact_object(self):
        from PIL import ImageFilter
        rng=np.random.default_rng(8)
        cloud=Image.fromarray(rng.integers(0,255,(128,128),dtype=np.uint8)).filter(ImageFilter.GaussianBlur(12))
        moved=cloud.transform(cloud.size,Image.Transform.AFFINE,(1,0,2,0,1,0),fillcolor=128)
        a=motion_array(cloud,True);b=motion_array(moved,True)
        self.assertEqual(motion_score(a,b,20,compact=True),0)
        object_frame=np.asarray(cloud).copy();object_frame[40:65,50:75]=240
        detail=motion_array(Image.fromarray(object_frame),True)
        self.assertGreater(motion_score(a,detail,20,compact=True),0.5)

    def test_scattered_tiny_changes_cannot_accumulate_into_cloud_trigger(self):
        base=np.full((128,128),100,dtype=np.uint8);changed=base.copy()
        for y in range(10,110,20):
            for x in range(10,110,20):changed[y:y+4,x:x+4]=220
        self.assertGreater(motion_score(base,changed,20),1)
        self.assertEqual(motion_score(base,changed,20,compact=True),0)

    def test_cloud_suppression_keeps_thin_plane_detail(self):
        base=np.full((360,640),100,dtype=np.uint8);changed=base.copy()
        changed[167:169,100:118]=220;changed[164:170,114:116]=220
        a=motion_array(Image.fromarray(base),True);b=motion_array(Image.fromarray(changed),True)
        self.assertGreater(motion_score(a,b,15,compact=True),0)

    def test_noise_and_exposure_rejected_object_detected(self):
        rng=np.random.default_rng(1)
        base=np.full((100,100),70,dtype=np.uint8)
        self.assertEqual(motion_score(base,base+40,25),0)
        noisy=np.clip(base.astype(int)+rng.integers(-4,5,base.shape),0,255).astype(np.uint8)
        self.assertEqual(motion_score(base,noisy,25),0)
        obj=base.copy();obj[10:30,20:40]=200
        self.assertGreater(motion_score(base,obj,25),3)
    def test_selected_target_follows_detail_and_reports_loss(self):
        from motion_trigger import SelectedTargetTracker
        rng=np.random.default_rng(77)
        detail=rng.integers(40,200,(16,16),dtype=np.uint8)
        a=np.zeros((120,180),dtype=np.uint8);a[42:58,62:78]=detail
        tracker=SelectedTargetTracker(Image.fromarray(a),70,50)
        b=np.zeros_like(a);b[48:64,69:85]=detail
        tracker.update(Image.fromarray(b))
        self.assertEqual((tracker.x,tracker.y),(77,56))
        self.assertEqual(tracker.state,'tracking')
        tracker.update(Image.fromarray(np.zeros_like(a)))
        self.assertEqual(tracker.state,'lost')
        with self.assertRaises(ValueError):SelectedTargetTracker(Image.fromarray(np.zeros_like(a)),50,50)

    def test_user_selection_records_when_automatic_motion_disabled(self):
        folder=self.root/'selected';folder.mkdir()
        self.station.active=dict(id='selected',started_monotonic=time.monotonic(),markers=[])
        event,before,after=self.event()
        event['user_selected']=True
        self.trigger.pending=(event,before,after)
        self.assertFalse(self.trigger.config['enabled'])
        self.trigger.tick()
        self.assertIsNone(self.trigger.pending)
        self.assertEqual(self.trigger.last_event['action'],'annotated_existing_recording')

    def test_click_selection_requests_capture_and_stop_clears_target(self):
        rng=np.random.default_rng(4)
        Image.fromarray(rng.integers(0,255,(120,180),dtype=np.uint8)).save(self.root/'preview.jpg')
        selected=self.trigger.select_target(dict(x=.5,y=.5))
        self.assertEqual(selected['state'],'tracking')
        self.assertTrue(self.trigger.pending[0]['user_selected'])
        self.assertEqual(self.trigger.pending[0]['algorithm'],'user-selected-template-v1')
        self.assertIsNotNone(self.trigger.overlay()['manual_target'])
        self.trigger.select_target(dict(stop=True))
        self.assertIsNone(self.trigger.manual_tracker)
        self.assertIsNone(self.trigger.manual_overlay)
        with self.assertRaises(ValueError):self.trigger.select_target(dict(x=2,y=.5))

    def test_small_trajectory_detects_motion_and_rejects_static_flicker(self):
        from motion_trigger import SmallMotionTracker
        def box(x,y):return dict(left=x,top=y,right=x+3,bottom=y+3,pixels=8)
        tracker=SmallMotionTracker()
        moving=[tracker.update([box(800-i*4,600+i*6)],i*.2) for i in range(8)]
        self.assertTrue(moving[-1])
        tracker=SmallMotionTracker()
        self.assertFalse(any(tracker.update([box(800,600)],i*.2) for i in range(10)))
        tracker=SmallMotionTracker()
        self.assertFalse(any(tracker.update([box(800+(i%2)*4,600)],i*.2) for i in range(10)))
        rng=np.random.default_rng(42);tracker=SmallMotionTracker()
        self.assertFalse(any(tracker.update([box(int(rng.integers(0,1920)),int(rng.integers(0,1080))) for j in range(20)],i*.2) for i in range(30)))

    def test_day_and_night_presets(self):
        self.trigger.configure({'pre_roll_seconds':15,'roi_top':10})
        night=self.trigger.configure({'filter_profile':'nighttime'})
        self.assertEqual(night['filter_profile'],'nighttime')
        self.assertTrue(night['cloud_suppression'])
        self.assertEqual(night['pre_roll_seconds'],15)
        self.assertEqual(night['roi_top'],10)
        day=self.trigger.configure({'filter_profile':'daytime'})
        self.assertGreater(day['pixel_threshold'],night['pixel_threshold'])
        self.assertLess(day['reference_seconds'],night['reference_seconds'])
        self.assertEqual(json.loads(self.trigger.path.read_text())['filter_profile'],'daytime')
        self.assertEqual(self.trigger.configure({'pixel_threshold':20})['filter_profile'],'custom')
        with self.assertRaises(ValueError):self.trigger.configure({'filter_profile':'invalid'})

    def test_settings_validation_and_persistence(self):
        for values in ({'analysis_fps':61},{'roi_left':95,'roi_right':96},
                       {'min_area_percent':10,'max_area_percent':5},{'pixel_threshold':float('nan')}):
            with self.assertRaises(ValueError):self.trigger.configure(values)
        self.trigger.configure({'duration_minutes':3,'analysis_fps':10})
        self.assertEqual(json.loads(self.trigger.path.read_text())['analysis_fps'],10)
    def event(self):
        return ({'id':'a'*16,'detected_at':'test','detected_epoch':time.time(),'changed_area_percent':2},b'before',b'after')
    def test_existing_session_keeps_fixed_duration_and_evidence_saved(self):
        folder=self.root/'session';folder.mkdir()
        self.station.active=dict(id='session',started_monotonic=time.monotonic()-50,
            duration_limit_seconds=100,markers=[])
        self.trigger.configure({'enabled':True})
        self.trigger.pending=self.event()
        self.trigger.tick()
        self.assertEqual(self.station.active['duration_limit_seconds'],100)
        self.assertEqual((folder/('motion-'+'a'*16+'-before.jpg')).read_bytes(),b'before')
        self.assertEqual(len(json.loads((folder/'motion-events.json').read_text())),1)
        self.assertEqual(self.trigger.last_event['action'],'annotated_existing_recording')
        self.assertIsNone(self.trigger.pending)
        self.trigger.pending=self.event()
        self.trigger.tick()
        self.assertEqual(self.station.active['duration_limit_seconds'],100)
    def test_priority_start_and_failed_capture_resume_export(self):
        self.trigger.configure({'enabled':True})
        self.station.start=Mock(side_effect=ValueError('no camera'))
        self.trigger.pending=self.event()
        self.trigger.tick()
        self.station.experiments.resume_exports.assert_called_once()
        self.assertIsNotNone(self.trigger.pending)
        self.assertEqual(self.trigger.phase,'waiting_for_capture')
    def test_stale_event_does_not_capture(self):
        self.trigger.configure({'enabled':True})
        e,b,a=self.event();e['detected_epoch']-=31
        self.trigger.pending=(e,b,a)
        self.trigger.tick()
        self.assertEqual(self.trigger.last_event['action'],'missed_capture')
        self.station.experiments.pause_exports.assert_not_called()
    def test_live_worker_confirms_moving_target(self):
        self.trigger.configure(dict(enabled=True,analysis_width=640,analysis_fps=20,reference_seconds=.1,
            confirmation_seconds=.1,min_area_percent=.1,cooldown_minutes=0))
        for i in range(30):
            a=np.full((360,640),60,dtype=np.uint8)
            x=20+i*8;a[100:140,x:x+40]=180
            tmp=self.root/'tmp.jpg';Image.fromarray(a).save(tmp);tmp.replace(self.root/'preview.jpg')
            time.sleep(.055)
            if self.trigger.pending:break
        self.assertIsNotNone(self.trigger.pending,self.trigger.status())

    def test_idle_trigger_starts_priority_recording(self):
        self.trigger.configure({'enabled':True})
        def start(body, motion_event):
            folder=self.root/'new-session';folder.mkdir()
            self.station.active=dict(id='new-session',started_monotonic=time.monotonic(),
                duration_limit_seconds=180,markers=[],capture_origin='motion_trigger')
        self.station.start=Mock(side_effect=start)
        self.trigger.pending=self.event()
        self.trigger.tick()
        self.station.experiments.pause_exports.assert_called_once()
        self.station.start.assert_called_once()
        self.assertEqual(self.trigger.last_event['action'],'started_recording')
        self.assertEqual(self.trigger.last_event['session_id'],'new-session')
        self.assertIsNone(self.trigger.pending)

    def test_small_fast_target_below_old_area_threshold(self):
        self.trigger.configure(dict(enabled=True,analysis_width=640,analysis_fps=60,reference_seconds=.1,
            confirmation_seconds=.1,min_area_percent=.01,pixel_threshold=15,cooldown_minutes=0))
        # A 6x6 analysis-pixel object is far below the old 0.5% threshold.
        for i in range(24):
            a=np.full((360,640),60,dtype=np.uint8)
            if i>=9:
                x=20+i*9;a[100:106,x:x+6]=140
            tmp=self.root/'tmp.jpg';Image.fromarray(a).save(tmp,quality=95);tmp.replace(self.root/'preview.jpg')
            time.sleep(.02)
            if self.trigger.pending:break
        self.assertIsNotNone(self.trigger.pending,self.trigger.status())
        self.assertLess(self.trigger.pending[0]['changed_area_percent'],.5)

    def test_excluded_foliage_does_not_trigger_but_sky_object_does(self):
        self.trigger.configure(dict(enabled=True,analysis_width=640,analysis_fps=30,reference_seconds=.1,
            confirmation_seconds=.1,min_area_percent=.01,pixel_threshold=15,
            cooldown_minutes=0,roi_bottom=68))
        def frame(i,bird=False):
            a=np.full((360,640),60,dtype=np.uint8)
            x=20+(i*9)%400
            a[280:330,x:x+40]=140
            if bird:a[100:106,x:x+6]=140
            tmp=self.root/'tmp.jpg';Image.fromarray(a).save(tmp,quality=95);tmp.replace(self.root/'preview.jpg')
            time.sleep(.04)
        for i in range(20):frame(i)
        self.assertIsNone(self.trigger.pending,self.trigger.status())
        for i in range(20):
            frame(i,True)
            if self.trigger.pending:break
        self.assertIsNotNone(self.trigger.pending,self.trigger.status())

    def test_thin_native_plane_silhouette_triggers(self):
        # Native-scale 18x4 silhouette: too thin for the old 5-neighbor filter.
        self.trigger.configure(dict(enabled=True,analysis_width=1920,analysis_fps=30,
            reference_seconds=.2,confirmation_seconds=.1,min_area_percent=.001,
            pixel_threshold=15,cooldown_minutes=0,roi_bottom=68))
        for i in range(30):
            a=np.full((1080,1920),95,dtype=np.uint8)
            if i>=9:
                x=150+i*5
                a[267:269,x:x+18]=60
                a[264:270,x+14:x+16]=60
            tmp=self.root/'tmp.jpg';Image.fromarray(a).save(tmp,quality=95);tmp.replace(self.root/'preview.jpg')
            time.sleep(.05)
            if self.trigger.pending:break
        self.assertIsNotNone(self.trigger.pending,self.trigger.status())
        self.assertLess(self.trigger.pending[0]['changed_area_percent'],.01)

    def test_components_separate_objects_and_map_native_roi(self):
        mask=np.zeros((20,30),dtype=bool);mask[2:5,3:8]=True;mask[12:16,20:25]=True
        boxes=changed_regions(mask)
        self.assertEqual(len(boxes),2)
        self.assertEqual(boxes[0],dict(left=20,top=12,right=25,bottom=16,pixels=20))
        self.assertEqual(boxes[1],dict(left=3,top=2,right=8,bottom=5,pixels=15))
    def test_annotation_saves_separate_frame_and_preserves_original(self):
        import io
        before=np.full((360,640),60,dtype=np.uint8);after=before.copy();after[90:100,220:240]=180
        def jpeg(a):
            b=io.BytesIO();Image.fromarray(a).save(b,format='JPEG',quality=95);return b.getvalue()
        b,a=jpeg(before),jpeg(after);original=a;target=self.root/'boxed.jpg'
        result=annotate_motion(b,a,dict(analysis_width=640,pixel_threshold=25,roi_left=20,roi_top=10,roi_right=90,roi_bottom=68),target)
        self.assertEqual(a,original)
        self.assertTrue(target.is_file())
        with Image.open(target) as image:self.assertEqual(image.size,(640,360))
        self.assertTrue(any(box['left']<=220 and box['right']>=239 and box['top']<=90 for box in result['boxes']))

    def test_disappearing_target_is_boxed_on_earlier_frame(self):
        import io
        base=np.full((180,320),150,dtype=np.uint8);bird=base.copy();bird[100:120,30:70]=30
        def jpeg(values):
            out=io.BytesIO();Image.fromarray(values).save(out,format='JPEG',quality=95);return out.getvalue()
        before,after=jpeg(bird),jpeg(base);target=self.root/'disappearing-boxed.jpg'
        result=annotate_motion(before,after,dict(analysis_width=320,pixel_threshold=20),target)
        self.assertEqual(result['source_frame'],'before')
        self.assertTrue(result['boxes'])
        with Image.open(target) as im:self.assertLess(im.getpixel((50,110))[0],60)
        arrival=annotate_motion(after,before,dict(analysis_width=320,pixel_threshold=20),self.root/'arriving-boxed.jpg')
        self.assertEqual(arrival['source_frame'],'after')

    def test_moved_target_does_not_get_an_empty_departure_box(self):
        import io
        before=np.full((180,320),150,dtype=np.uint8);after=before.copy()
        before[60:80,20:50]=20;after[60:80,180:210]=20
        def jpeg(values):
            out=io.BytesIO();Image.fromarray(values).save(out,format='JPEG',quality=95);return out.getvalue()
        result=annotate_motion(jpeg(before),jpeg(after),dict(analysis_width=320,pixel_threshold=20),self.root/'moving-boxed.jpg')
        self.assertEqual(result['source_frame'],'after')
        self.assertTrue(all(box['left']>100 for box in result['boxes']))
        self.assertTrue(any(box['visible_in']=='before' for box in result['changed_regions']))

    def test_motion_window_follows_last_motion_then_exact_postroll(self):
        active=dict(motion_onset_epoch=100,post_roll_seconds=10)
        self.trigger.last_motion_epoch=100
        self.assertEqual(self.trigger.recording_end(active),110)
        self.trigger.last_motion_epoch=105
        self.assertEqual(self.trigger.recording_end(active),115)
        # Wall-clock passage or repeated monitor ticks do not move the deadline.
        for _ in range(5):self.assertEqual(self.trigger.recording_end(active),115)
        active['rf_required_until_epoch']=200
        self.assertEqual(self.trigger.recording_end(active),200)

    def test_polygon_validation_rejects_crossing_or_degenerate_borders(self):
        for points in ([],[[0,0],[100,100],[0,100],[100,0]],[[0,0],[0,0],[100,100]],
                       [[0,0],[1,0],[1,1]],[[0,0],[100,float('nan')],[100,100]],[[0,0],[101,0],[50,50]]):
            with self.assertRaises(ValueError):validate_polygon(points)
        points=[[0,0],[100,0],[100,40],[40,40],[40,100],[0,100]]
        self.assertEqual(validate_polygon(points),points)
    def test_concave_polygon_excludes_motion_and_exposure_outside_border(self):
        cfg=dict(roi_polygon=[[0,0],[100,0],[100,40],[40,40],[40,100],[0,100]])
        bounds,mask=region_geometry(cfg,640,360)
        self.assertEqual(bounds,(0,0,640,360))
        base=np.full((360,640),60,dtype=np.uint8)
        after=base.copy();after[200:250,400:500]=200
        self.assertEqual(motion_score(base,after,15,mask),0)
        after[40:50,400:420]=200
        self.assertGreater(motion_score(base,after,15,mask),0)
    def test_polygon_persists_and_other_settings_keep_border(self):
        polygon=[[0,0],[100,0],[100,68],[40,55],[0,68]]
        self.trigger.configure(dict(roi_polygon=polygon))
        self.trigger.configure(dict(pixel_threshold=20))
        self.assertEqual(self.trigger.config['roi_polygon'],polygon)
        self.assertEqual(json.loads(self.trigger.path.read_text())['roi_polygon'],polygon)
        self.trigger.configure(dict(roi_bottom=60))
        self.assertIsNone(self.trigger.config['roi_polygon'])
    def test_polygon_annotation_does_not_box_excluded_motion(self):
        import io
        base=np.full((360,640),60,dtype=np.uint8);after=base.copy();after[200:230,400:440]=200
        def jpeg(a):
            b=io.BytesIO();Image.fromarray(a).save(b,format='JPEG',quality=95);return b.getvalue()
        cfg=dict(analysis_width=640,pixel_threshold=15,roi_polygon=[[0,0],[100,0],[100,40],[40,40],[40,100],[0,100]])
        result=annotate_motion(jpeg(base),jpeg(after),cfg,self.root/'poly.jpg')
        self.assertEqual(result['boxes'],[])

    def test_idle_recorder_rearms_even_without_quiet_background(self):
        self.trigger.configure(dict(enabled=True,cooldown_minutes=0))
        self.trigger.latched=True;self.trigger.quiet_since=None;self.trigger.candidate_since=123
        self.trigger.tick()
        self.assertFalse(self.trigger.latched)
        self.assertIsNone(self.trigger.candidate_since)
        self.assertEqual(self.trigger.phase,'armed')
    def test_active_recording_keeps_latch_to_avoid_duplicate_events(self):
        self.trigger.configure(dict(enabled=True))
        self.station.active=dict(id='recording');self.trigger.latched=True
        self.trigger.tick();self.assertTrue(self.trigger.latched)


class GroupedReviewTests(TestCase):
    def test_fragments_join_but_distant_objects_remain_separate(self):
        from motion_trigger import group_regions
        boxes=[dict(left=10,top=10,right=20,bottom=20,pixels=30),
               dict(left=24,top=12,right=30,bottom=22,pixels=24),
               dict(left=100,top=100,right=110,bottom=110,pixels=30)]
        groups=group_regions(boxes)
        self.assertEqual(len(groups),2)
        self.assertEqual(groups[0]['pixels'],54)
        self.assertEqual(groups[0]['right'],30)

    def test_sparse_cloud_edge_rejected_even_when_large(self):
        from motion_trigger import compact_region
        self.assertFalse(compact_region(dict(left=0,top=0,right=98,bottom=199,pixels=1307)))
        self.assertTrue(compact_region(dict(left=0,top=0,right=118,bottom=41,pixels=1158)))
        self.assertTrue(compact_region(dict(left=0,top=0,right=17,bottom=10,pixels=33)))
