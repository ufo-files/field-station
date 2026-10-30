import tempfile,threading,time,math
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from PIL import Image,ImageDraw
from experiments import load
from lab_capture import LabCapture

class LabCaptureTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.preview=self.root/'preview.jpg'
        im=Image.new('RGB',(160,120),'black');ImageDraw.Draw(im).ellipse((40,40,60,60),fill='white');im.save(self.preview)
        self.station=SimpleNamespace(lock=threading.RLock(),active=None,motion_trigger=SimpleNamespace(config=dict(pre_roll_seconds=10,post_roll_seconds=10),last_motion_epoch=None),experiments=SimpleNamespace(pause_exports=lambda:True,resume_exports=lambda:None),data_path=lambda sid:self.root/sid)
        self.starts=[]
        def start(body,motion_event):
            self.starts.append(motion_event);sid='20261028T230000Z-abcdef';(self.root/sid).mkdir();self.station.active=dict(id=sid,started_epoch=time.time()-10,markers=[],capture_origin='motion_trigger');return self.station.active
        self.station.start=start;self.capture=LabCapture(self.station,self.preview)
    def tearDown(self):self.tmp.cleanup()
    def body(self):return dict(model_id='a'*32,width=160,height=120,objects=[dict(label='anomalous',score=.98,detail_score=.9,box=[40,40,20,20])])
    def test_capture_preserves_native_evidence_and_model_provenance(self):
        response=self.capture.receive(self.body());folder=self.root/response['session_id'];events=load(folder/'motion-events.json');self.assertEqual(len(self.starts),1);self.assertEqual(len(events),1)
        self.assertEqual(events[0]['classification']['source'],'uap-lab');self.assertEqual(events[0]['model_version'],'a'*32);self.assertNotIn('human_review',events[0])
        self.assertEqual(self.station.active['capture_origin'],'lab_model');self.assertTrue((folder/'model-frames/detections.jsonl').exists());self.assertEqual(response['rf_log'],'rf.jsonl')
        im=Image.open(folder/f"motion-{response['event_id']}-after.jpg");self.assertEqual(im.size,(160,120));im.close()
        self.capture.receive(self.body());self.assertEqual(len(self.starts),1);self.assertEqual(len(load(folder/'motion-events.json')),1)
        self.station.active=None;self.assertEqual(self.capture.receive(self.body())['state'],'cooldown');self.assertEqual(len(self.starts),1)
    def test_bad_models_scores_and_dimensions_never_capture(self):
        for change in (dict(objects=[dict(label='anomalous',score=.999,detail_score=.1,box=[40,40,20,20])]),dict(model_id='../bad'),dict(width=161),dict(objects=[dict(label='bird',score=.99,detail_score=.9,box=[40,40,20,20])]),dict(objects=[dict(label='anomalous',score=float('nan'),box=[40,40,20,20])])):
            body=self.body();body.update(change)
            with self.assertRaises(ValueError):self.capture.receive(body)
        self.assertFalse(self.starts)
    def test_multiple_confirmed_targets_keep_ids_and_saved_regions(self):
        body=self.body();body['objects'][0]['target_id']=11;body['objects'].append(dict(label='anomalous',score=.99,detail_score=.9,box=[90,50,16,16],target_id=12))
        first=self.capture.receive(body);self.assertEqual(first['target_count'],2)
        folder=self.root/first['session_id'];events=load(folder/'motion-events.json');self.assertEqual(len(events[0]['classification']['regions']),2)
        body['objects'].append(dict(label='anomalous',score=.99,detail_score=.9,box=[115,65,16,16],target_id=13))
        second=self.capture.receive(body);self.assertEqual(second['target_count'],3);self.assertEqual(second['target_ids'],[11,12,13]);self.assertEqual(len(self.starts),1)
        lines=(folder/'model-frames/detections.jsonl').read_text().splitlines()
        import json
        self.assertEqual(len(json.loads(lines[-1])['regions']),3)
