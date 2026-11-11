import json,tempfile,unittest
from pathlib import Path
from cascade_training import freeze_inputs,build_snapshot
class CascadeDatasetTests(unittest.TestCase):
 def test_frozen_machine_labels_human_override_and_four_distinct_snapshots(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);source=root/'stable';(source/'images').mkdir(parents=True)
   samples=[]
   for i,label in enumerate(['anomalous','not_anomalous']):
    (source/'images'/str(i)).write_bytes(bytes([i]));samples.append(dict(origin='email:'+str(i),label=label,group='g'+str(i),image='images/'+str(i),human_confirmed=True,pixel_sha256='human'+str(i),native_width=8,native_height=8,split='train'))
   (source/'dataset.json').write_text(json.dumps(dict(fingerprint='base',samples=samples,classes=['anomalous','not_anomalous'])))
   (source/'candidate-policy.json').write_text(json.dumps(dict(version='stable')))
   cfg={'code':str(Path(__file__).resolve().parents[1]),'cycle_root':str(root/'cycles'),'lanes':{lane:{'root':str(root/lane)} for lane in ['experimental','hybrid','machine']}}
   for lane in ['hybrid','machine']:
    corpus=root/lane/'corpus';corpus.mkdir(parents=True);rows={}
    for i,label in enumerate(['anomalous','not_anomalous']):
     (corpus/str(i)).write_bytes(bytes([i+2]));rows[str(i)]=dict(id='m'+str(i),image=str(i),label=label,generation='run',human_confirmed=False,label_source='machine',pixel_sha256='machine'+str(i),native_width=8,native_height=8)
    (corpus/'manifest.json').write_text(json.dumps(rows))
   cycle=dict(id='one',stable_source=str(source),inputs=freeze_inputs(cfg,'one'))
   # Later collection must not change this cycle's source labels.
   (root/'machine/corpus/manifest.json').write_text('{}')
   paths=[build_snapshot(cfg,cycle,lane) for lane in ['experimental','hybrid','machine']]
   data=[json.loads((p/'dataset.json').read_text()) for p in paths]
   self.assertEqual(len({d['fingerprint'] for d in data}),3)
   self.assertTrue(all(r['human_confirmed'] for r in data[0]['samples']))
   self.assertEqual(len(data[1]['samples']),4)
   self.assertTrue(all(not r['human_confirmed'] and r['label_source']=='machine' for r in data[2]['samples']))
   self.assertEqual(data[2]['evaluation_mode'],'shared_human_benchmark')
   self.assertEqual(paths[0],build_snapshot(cfg,cycle,'experimental'))
   next_cycle=dict(cycle,id='two');self.assertNotEqual(paths[0],build_snapshot(cfg,next_cycle,'experimental'))
