import os,tempfile,unittest,json
from pathlib import Path
os.environ['UAP_LAB_DATA']=tempfile.mkdtemp(prefix='uap-lab-test-')
os.environ['UAP_LAB_RESERVE_BYTES']='0'
import lab
import cv2,numpy as np
class PipelineTest(unittest.TestCase):
    def test_native_pipeline_and_boundary_exports(self):
        vid='1'*32;folder=lab.video_path(vid);folder.mkdir();images=folder/'input';images.mkdir()
        rng=np.random.default_rng(41);target=rng.integers(20,240,(16,16,3),dtype=np.uint8)
        # A moving target visible only in the middle, with true negative boundary frames.
        for i in range(7):
            frame=np.full((96,128,3),12,np.uint8)
            if 2<=i<=4:frame[30:46,20+i*5:36+i*5]=target
            cv2.imwrite(str(images/f'{i:03d}.png'),frame)
        lab.run_command([lab.FFMPEG,'-v','error','-framerate','7','-i',str(images/'%03d.png'),'-c:v','libx264','-crf','0','-pix_fmt','yuv420p','-threads','1','-y',str(folder/'source.mp4')])
        (folder/'source.mp4').rename(folder/'source');meta=lab.probe(folder/'source');meta.update(id=vid,name='fixture',created=0);lab.save(folder/'video.json',meta)
        lab.annotate(vid,2/7,dict(x=30/128,y=30/96,w=16/128,h=16/96),'anomalous');model=lab.train()
        rid='2'*32;out=lab.DATA/'runs'/rid;out.mkdir();lab.evaluate(rid,vid,model,.9,['anomalous'])
        result=lab.read(out/'run.json');self.assertEqual(result['state'],'complete',result)
        self.assertEqual(result['frame_count'],7);self.assertEqual(result['detected_frames'],3)
        event=result['segments'][0];self.assertEqual((event['first_detected'],event['last_detected']),(2,4));self.assertEqual((event['first_saved'],event['last_saved']),(1,5))
        self.assertEqual(len(list((out/event['frames']).glob('*.png'))),5)
        full=lab.probe(out/event['full_size']);self.assertEqual((full['width'],full['height']),(128,96))
        crop=lab.probe(out/event['crops'][0]['file']);self.assertLess(crop['width'],128)
        self.assertAlmostEqual(full['duration'],5/7,places=4)
        for path in (out/event['full_size'],out/event['crops'][0]['file']):
            info=json.loads(lab.run_command([lab.FFPROBE,'-v','error','-count_frames','-show_streams','-of','json',str(path)]));self.assertEqual(int(info['streams'][0]['nb_read_frames']),5)
        times=lab.read(out/'timestamps.json')['times'];self.assertAlmostEqual(times[1]-times[0],1/7,places=5)
        # Tree is a selectable, trainable label and model versions are immutable.
        lab.annotate(vid,2/7,dict(x=30/128,y=30/96,w=16/128,h=16/96),'tree');new=lab.train();self.assertIn('tree',new['classes']);self.assertNotEqual(model['id'],new['id']);self.assertEqual(len(model['examples']),1)
    def test_validation_and_boundaries(self):
        self.assertEqual(lab.groups([0,1,4,5,8]),[[0,1],[4,5],[8]])
        for value in ('../secret','x'*32,''):
            with self.assertRaises(ValueError):lab.checked_id(value)
        plain=np.zeros((32,32,3),np.uint8);template=np.zeros((5,5),np.uint8)
        self.assertEqual(lab.detect(plain,[('anomalous',template)],.85,['anomalous']),[])
    def test_variable_rate_timing_is_preserved(self):
        folder=lab.DATA/'vfr';folder.mkdir();files=[]
        for i in range(4):
            path=folder/f'{i}.png';cv2.imwrite(str(path),np.full((64,64,3),i*50,np.uint8));files.append(path)
        times=[0,.04,.16,.20];dest=folder/'native.mp4'
        lab.concat_video(files,times,dest,4)
        info=json.loads(lab.run_command([lab.FFPROBE,'-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(dest)]))
        actual=[float(v['best_effort_timestamp_time']) for v in info['frames']]
        self.assertEqual(len(actual),4)
        for a,b in zip(actual,times):self.assertAlmostEqual(a,b,places=4)
        (folder/'source').hardlink_to(dest)
        for a,b in zip(lab.timeline(folder),times):self.assertAlmostEqual(a,b,places=4)
        self.assertAlmostEqual(lab.probe(dest)['duration'],.24,places=4)
    def test_browser_preview_keeps_original(self):
        folder=lab.DATA/'preview-test';folder.mkdir()
        raw=np.random.default_rng(21).integers(0,255,(48,64,3),dtype=np.uint8)
        cv2.imwrite(str(folder/'frame.png'),raw)
        lab.run_command([lab.FFMPEG,'-v','error','-loop','1','-i',str(folder/'frame.png'),'-t','0.2','-c:v','mpeg4','-threads','1','-y',str(folder/'source.avi')])
        (folder/'source.avi').rename(folder/'source');original=(folder/'source').read_bytes()
        lab.save(folder/'video.json',dict(preview_state='preparing'))
        lab.prepare_preview(folder)
        self.assertEqual(lab.read(folder/'video.json')['preview_state'],'ready')
        self.assertEqual((folder/'source').read_bytes(),original)
        self.assertEqual(lab.probe(folder/'preview.mp4')['codec'],'h264')
if __name__=='__main__':unittest.main()

class ConfirmationTests(unittest.TestCase):
    def test_only_consistent_repeated_anomalous_matches_confirm(self):
        from live_monitor import Confirmation
        gate=Confirmation();m=[dict(label='anomalous',score=.99,box=[20,20,12,12])]
        self.assertFalse(gate.update(m,1));self.assertFalse(gate.update(m,2));self.assertTrue(gate.update(m,3))
        self.assertFalse(gate.update([],4));self.assertFalse(gate.update(m,5))
        self.assertFalse(gate.update([dict(label='bird',score=.99,box=[20,20,12,12])],6))

class MultipleTargetTests(unittest.TestCase):
    def setUp(self):
        self.previous_data=lab.DATA;self.tmp=tempfile.TemporaryDirectory(prefix='uap-multiple-');lab.DATA=Path(self.tmp.name)
        for name in ('videos','models','runs'):(lab.DATA/name).mkdir()
    def tearDown(self):
        lab.DATA=self.previous_data;self.tmp.cleanup()
    def test_independent_confirmation_when_match_scores_alternate(self):
        from live_monitor import Confirmation
        gate=Confirmation();a=dict(label='anomalous',score=.99,box=[10,10,12,12]);b=dict(label='anomalous',score=.98,box=[250,10,12,12])
        self.assertFalse(gate.update([a,b],1));self.assertFalse(gate.update([b,a],2));self.assertTrue(gate.update([a,b],3));self.assertEqual(len(gate.confirmed),2)
        original={m['target_id'] for m in gate.confirmed}
        c=dict(label='anomalous',score=1,box=[500,10,12,12]);self.assertTrue(gate.update([c,b,a],4));self.assertEqual({m['target_id'] for m in gate.confirmed},original)
        self.assertTrue(gate.update([a,c,b],5));self.assertEqual(len(gate.confirmed),2)
        self.assertTrue(gate.update([c,b,a],6));self.assertEqual(len(gate.confirmed),3)
    def test_two_objects_save_two_cropped_videos_and_idempotent_examples(self):
        vid='3'*32;folder=lab.video_path(vid);folder.mkdir();images=folder/'input';images.mkdir()
        rng=np.random.default_rng(72);target=rng.integers(10,240,(16,16,3),dtype=np.uint8)
        for i in range(5):
            frame=np.full((128,256,3),12,np.uint8)
            if 1<=i<=3:
                frame[20:36,20+i*2:36+i*2]=target
                frame[80:96,190-i*2:206-i*2]=target
            cv2.imwrite(str(images/f'{i:03d}.png'),frame)
        lab.run_command([lab.FFMPEG,'-v','error','-framerate','5','-i',str(images/'%03d.png'),'-c:v','libx264','-crf','0','-pix_fmt','yuv420p','-threads','1','-y',str(folder/'source.mp4')]);(folder/'source.mp4').rename(folder/'source')
        meta=lab.probe(folder/'source');meta.update(id=vid,name='two targets',created=1);lab.save(folder/'video.json',meta)
        for aid,box in (('a'*32,dict(x=22/256,y=20/128,w=16/256,h=16/128)),('b'*32,dict(x=188/256,y=80/128,w=16/256,h=16/128))):
            lab.annotate(vid,.2,box,'anomalous',aid);lab.annotate(vid,.2,box,'anomalous',aid)
        self.assertEqual(len(lab.read(folder/'annotations.json')),2)
        model=lab.train();rid='4'*32;out=lab.DATA/'runs'/rid;out.mkdir();lab.evaluate(rid,vid,model,.9,['anomalous']);result=lab.read(out/'run.json')
        self.assertEqual(result['state'],'complete',result);self.assertEqual(len(result['segments']),1);event=result['segments'][0];self.assertEqual(len(event['crops']),2)
        self.assertEqual((event['first_saved'],event['last_saved']),(0,4))
        rows=[json.loads(v) for v in (out/'detections.jsonl').read_text().splitlines()];self.assertEqual([len(r['objects']) for r in rows],[0,2,2,2,0])
        for c in event['crops']:self.assertTrue((out/c['file']).is_file())
    def test_omitted_videos_are_excluded_without_changing_existing_models(self):
        for vid,sha in (('5'*32,'a'*64),('6'*32,'b'*64)):
            folder=lab.video_path(vid);folder.mkdir();lab.save(folder/'video.json',dict(sha256=sha))
            cv2.imwrite(str(folder/'target.png'),np.random.default_rng(9).integers(0,255,(16,16,3),dtype=np.uint8))
            lab.save(folder/'annotations.json',[dict(id='a'*32,image='target.png',label='anomalous')])
        old=lab.train();self.assertEqual(len(old['examples']),2)
        lab.save(lab.video_path('5'*32)/'training-excluded.json',dict(excluded=True))
        new=lab.train();self.assertEqual(len(new['examples']),1);self.assertEqual(new['examples'][0]['video_id'],'6'*32)
        self.assertEqual(len(lab.read(lab.DATA/'models'/old['id']/'model.json')['examples']),2)
        lab.save(lab.DATA/'omitted-videos.json',{'b'*64:dict(excluded=True)})
        with self.assertRaisesRegex(ValueError,'at least one target'):lab.train()

class ReviewPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.previous=lab.DATA;self.tmp=tempfile.TemporaryDirectory(prefix='uap-review-speed-');lab.DATA=Path(self.tmp.name)
        for name in ('videos','models','runs'):(lab.DATA/name).mkdir()
        self.vid='7'*32;self.folder=lab.video_path(self.vid);self.folder.mkdir();(self.folder/'source').write_bytes(b'fixture source')
        lab.save(self.folder/'video.json',dict(duration=1,sha256='e'*64))
        self.raw=cv2.imencode('.png',np.random.default_rng(12).integers(0,255,(64,64,3),dtype=np.uint8))[1].tobytes()
    def tearDown(self):lab.DATA=self.previous;self.tmp.cleanup()
    def targets(self):return [dict(id=f'{i:032x}',time=.25,label='anomalous',bounds=dict(x=.01*i,y=.1,w=.1,h=.1)) for i in range(1,12)]
    def test_eleven_targets_decode_once_and_retry_is_idempotent(self):
        from unittest.mock import patch
        with patch.object(lab,'run_command',return_value=self.raw) as command:
            lab.complete_review(self.vid,self.targets());self.assertEqual(command.call_count,1)
            lab.complete_review(self.vid,self.targets());self.assertEqual(command.call_count,1)
        self.assertEqual(len(lab.read(self.folder/'annotations.json')),11)
        p=lab.read(self.folder/'review-progress.json');self.assertEqual((p['state'],p['completed'],p['total']),('complete',11,11))
    def test_preview_frame_is_reused_by_saving(self):
        from unittest.mock import patch
        with patch.object(lab,'run_command',return_value=self.raw) as command:
            lab.frame_at(self.folder,.25);command.reset_mock();lab.complete_review(self.vid,self.targets());command.assert_not_called()
    def test_concurrent_timeline_requests_demux_only_once(self):
        from unittest.mock import patch
        from concurrent.futures import ThreadPoolExecutor
        raw=json.dumps(dict(packets=[dict(pts_time='0'),dict(pts_time='.08'),dict(pts_time='.04'),dict(pts_time='-.04',flags='D')])).encode()
        with patch.object(lab,'run_command',return_value=raw) as command:
            with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:lab.timeline(self.folder),range(4)))
            self.assertEqual(command.call_count,1);self.assertIn('-show_packets',command.call_args.args[0]);self.assertNotIn('-show_frames',command.call_args.args[0])
        self.assertEqual(results,[[0,.04,.08]]*4)

class GenericIntakeTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        self.previous=lab.DATA;self.tmp=tempfile.TemporaryDirectory(prefix='uap-intake-');lab.DATA=Path(self.tmp.name)/'library';lab.DATA.mkdir()
        for name in ('videos','models','runs'):(lab.DATA/name).mkdir()
        self.input=Path(self.tmp.name)/'new-video.mp4';self.input.write_bytes(b'video content A')
        self.patcher=patch.object(lab,'probe',side_effect=lambda path:dict(duration=3,width=64,height=64,codec='h264',fps='30/1'));self.probe=self.patcher.start()
    def tearDown(self):self.patcher.stop();lab.DATA=self.previous;self.tmp.cleanup()
    def test_renamed_reviewed_video_is_not_imported_or_queued_again(self):
        import shutil
        original,created=lab.import_training_file(self.input);self.assertTrue(created);lab.complete_review(original['id'],[],no_target=True)
        renamed=self.input.with_name('renamed-copy.mp4');shutil.copyfile(self.input,renamed)
        duplicate,created=lab.import_training_file(renamed);self.assertFalse(created);self.assertEqual(duplicate['id'],original['id'])
        # Read the durable registries again as a fresh watcher/browser would after restart.
        videos=lab.library_videos();self.assertEqual(len(videos),1);self.assertTrue(videos[0]['review']['completed'])
        self.assertEqual(lab.read(lab.DATA/'reviewed-videos.json')[original['sha256']]['completed'],True)
        again,created=lab.import_training_file(self.input);self.assertFalse(created);self.assertEqual(again['id'],original['id']);self.assertEqual(self.probe.call_count,1)
    def test_new_content_at_reviewed_filename_is_new_video(self):
        first,_=lab.import_training_file(self.input);lab.complete_review(first['id'],[],no_target=True)
        self.input.write_bytes(b'different new video content B')
        second,created=lab.import_training_file(self.input);self.assertTrue(created);self.assertNotEqual(first['id'],second['id'])
        self.assertEqual((lab.video_path(first['id'])/'source').read_bytes(),b'video content A')
        videos=lab.library_videos();queue=[v for v in videos if not v['review'].get('completed') and not v['training_excluded']]
        self.assertEqual([v['id'] for v in queue],[second['id']])
    def test_legacy_per_video_review_is_reconciled_by_checksum(self):
        meta,_=lab.import_training_file(self.input);lab.save(lab.video_path(meta['id'])/'review.json',dict(completed=True,reviewed_at=100))
        self.assertFalse((lab.DATA/'reviewed-videos.json').exists());videos=lab.library_videos();self.assertTrue(videos[0]['review']['completed'])
        self.assertTrue(lab.read(lab.DATA/'reviewed-videos.json')[meta['sha256']]['completed'])
    def test_arbitrary_source_examples_are_used_in_training(self):
        meta,_=lab.import_training_file(self.input);folder=lab.video_path(meta['id'])
        cv2.imwrite(str(folder/'example.png'),np.random.default_rng(21).integers(0,255,(16,16,3),dtype=np.uint8))
        lab.save(folder/'annotations.json',[dict(id='a'*32,image='example.png',label='anomalous')]);lab.complete_review(meta['id'],[])
        model=lab.train();self.assertEqual(len(model['examples']),1);self.assertEqual(model['examples'][0]['video_id'],meta['id']);self.assertEqual(meta['provenance']['collection'],'training-data')
