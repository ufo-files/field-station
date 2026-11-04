import copy,json,tempfile,unittest
from pathlib import Path
from training_benchmark import select
class TrainingBenchmarkTests(unittest.TestCase):
 def dataset(self,n=700):
  return dict(fingerprint='dataset',classes=['anomalous','not_anomalous'],samples=[dict(image=f'images/{i}.png',origin=str(i),label='anomalous' if i%20==0 else 'not_anomalous',pixel_sha256=str(i),split='train') for i in range(n)]+[dict(image='holdout.png',origin='holdout',label='anomalous',pixel_sha256='holdout',split='test')])
 def test_500_training_images_shared_and_reproducible(self):
  with tempfile.TemporaryDirectory() as t:
   data=self.dataset();rows,meta=select(data,t)
   self.assertEqual(len(rows),500);self.assertEqual(len({r['image'] for r in rows}),500)
   self.assertTrue(all(r['split']=='train' for r in rows));self.assertEqual(meta['kind'],'random_training_sample')
   data['samples'].reverse();again,again_meta=select(data,t)
   self.assertEqual(rows,again);self.assertEqual(meta,again_meta)
   self.assertEqual(len(json.loads((Path(t)/'training-benchmark.json').read_text())['samples']),500)
 def test_smaller_dataset_is_explicit_and_never_padded(self):
  with tempfile.TemporaryDirectory() as t:
   rows,meta=select(self.dataset(40),t);self.assertEqual(len(rows),40);self.assertEqual(meta['count'],40);self.assertEqual(meta['requested_count'],500)
 def test_corrected_label_or_replaced_dataset_cannot_silently_redraw(self):
  with tempfile.TemporaryDirectory() as t:
   data=self.dataset(40);select(data,t);data['samples'][0]['label']='not_anomalous'
   with self.assertRaisesRegex(ValueError,'label changed'):select(data,t)
   data=self.dataset(40);data['fingerprint']='replacement'
   with self.assertRaisesRegex(ValueError,'identity changed'):select(data,t)
 def test_empty_training_pool_is_not_replaced_by_holdout(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):select(self.dataset(0),t)
