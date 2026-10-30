import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import cv2,numpy as np
import lab,export_public_model
from model_publisher import ModelPublisher

class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.previous=lab.DATA;self.export_data=export_public_model.DATA;lab.DATA=Path(self.temp.name)
        for name in ('videos','models','runs','publication'):(lab.DATA/name).mkdir()
        self.vid='b'*32;folder=lab.video_path(self.vid);folder.mkdir()
        lab.save(folder/'video.json',dict(name='private-source-name.mp4',sha256='c'*64,provenance=dict(collection='training-data',local_file='/home/hackrf/private-video.mp4')))
        self.image=np.random.default_rng(21).integers(0,255,(20,20,3),dtype=np.uint8);cv2.imwrite(str(folder/'crop.png'),self.image)
        lab.save(folder/'annotations.json',[dict(id='d'*32,image='crop.png',label='anomalous',time=1,bounds=dict(x=.1,y=.1,w=.1,h=.1))])
        lab.save(lab.DATA/'publication/config.json',dict(enabled=True,repository='ufo-files/uap-observation-model'))
    def tearDown(self):lab.DATA=self.previous;export_public_model.DATA=self.export_data;self.temp.cleanup()
    def test_save_enqueues_each_version_durably(self):
        first=lab.train();second=lab.train();outbox=lab.DATA/'publication/outbox'
        self.assertEqual(len(list(outbox.glob('*.json'))),2)
        lab.queue_model_publication(first);self.assertEqual(len(list(outbox.glob('*.json'))),2)
        self.assertEqual(lab.read(outbox/(second['id']+'.json'))['state'],'queued')
    def test_export_uses_saved_pixels_and_omits_private_paths(self):
        model=lab.train();original=(lab.DATA/'models'/model['id']/model['examples'][0]['image']).read_bytes()
        cv2.imwrite(str(lab.video_path(self.vid)/'crop.png'),np.zeros((20,20,3),np.uint8))
        export_public_model.DATA=lab.DATA;out=lab.DATA/'export';summary=export_public_model.build_saved(model['id'],out);published=lab.read(out/'model.json')
        self.assertEqual(published['id'],model['id']);self.assertEqual(summary['examples'],1)
        self.assertEqual((out/published['examples'][0]['image']).read_bytes(),original)
        sources=(out/'sources.json').read_text();self.assertNotIn('/home/hackrf',sources);self.assertNotIn('private-source-name',sources)
    def test_retry_preserves_commit_and_version_receipt(self):
        model=lab.train();publisher=ModelPublisher(start_worker=False);calls=[];fail=[True]
        def command(args,timeout=180):
            calls.append(args)
            if args[:2]==['git','clone']:
                gitdir=Path(args[-1])/'.git';gitdir.mkdir(parents=True);(gitdir/'HEAD').write_text('ref: refs/heads/main')
            if args[:4]==['git','diff','--cached','--name-only']:return 'model.json'
            if args[:3]==['git','rev-parse','HEAD']:return 'f'*40
            if args[:2]==['git','push'] and fail[0]:fail[0]=False;raise RuntimeError('temporary network failure')
            return ''
        publisher.command=command
        with patch.object(export_public_model,'build_saved',wraps=export_public_model.build_saved) as build:
            publisher.tick();path=publisher.root/'outbox'/(model['id']+'.json');request=lab.read(path)
            self.assertEqual(request['state'],'failed');self.assertEqual(request['commit'],'f'*40)
            request['retry_at']=0;lab.save(path,request);publisher.tick();self.assertEqual(build.call_count,1)
        receipt=lab.read(publisher.root/'receipts'/(model['id']+'.json'));self.assertEqual(receipt['state'],'published');self.assertIn('model-'+model['id'],receipt['url']);self.assertEqual(publisher.status()['pending'],0)
if __name__=='__main__':unittest.main()
