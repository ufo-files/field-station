import hashlib,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from corpus import preserve,machine_dataset
CODE=Path(__file__).resolve().parents[1]
class CorpusTests(unittest.TestCase):
 def make(self,root,i,label='anomalous',group='one'):
  frames=root/'frames';frames.mkdir(exist_ok=True);im=Image.new('RGB',(8,8),(i,0,0));im.save(frames/(str(i)+'.png'))
  return dict(id=str(i),pixel_sha256=hashlib.sha256(b'8x8:RGB:'+im.tobytes()).hexdigest(),label=label,generation=group,native_width=8,native_height=8,teacher_version='seed')
 def test_preserved_pixels_survive_collection_cache_changes(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);row=self.make(root,1);data=preserve(root,[row],root/'frames');p=root/'corpus'/next(iter(data.values()))['image'];original=p.read_bytes();(root/'frames/1.png').write_bytes(b'changed');self.assertEqual(p.read_bytes(),original)
 def test_human_labels_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);row=self.make(root,1);row['human_confirmed']=True
   with self.assertRaises(ValueError):preserve(root,[row],root/'frames')
 def test_machine_splits_preserve_groups_and_exclude_human_rows(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);rows=[self.make(root,i,'anomalous' if i%2 else 'not_anomalous',str(i//2)) for i in range(16)]
   preserve(root,rows,root/'frames');folder,blockers=machine_dataset(root,CODE);self.assertFalse(blockers)
   data=json.loads((folder/'dataset.json').read_text());self.assertTrue(all(not r['human_confirmed'] and r['label_source']=='machine' for r in data['samples']))
   for group in {r['group'] for r in data['samples']}:self.assertEqual(len({r['split'] for r in data['samples'] if r['group']==group}),1)
   self.assertEqual(data['human_training_counts'],{})
 def test_one_recording_is_preserved_but_not_trainable(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);preserve(root,[self.make(root,1),self.make(root,2,'not_anomalous')],root/'frames');folder,blockers=machine_dataset(root,CODE);self.assertTrue(blockers);self.assertTrue((folder/'dataset.json').exists())
