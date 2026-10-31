import hashlib,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from dataset import build
class DatasetTests(unittest.TestCase):
 def row(self,root,name,label,group,split=None,color=0):
  im=Image.new('RGB',(8,8),(color,20,30));im.save(root/(name+'.png'))
  row=dict(origin=name,image=name+'.png',label=label,group=group,pixel_sha256=hashlib.sha256(b'8x8:RGB:'+im.tobytes()).hexdigest(),native_width=8,native_height=8)
  if split:row['split']=split
  return row
 def test_frozen_splits_and_corrections(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);base=root/'base';reviews=root/'reviews';base.mkdir();reviews.mkdir()
   rows=[self.row(base,'b'+str(i),'cloud','recording'+str(i),role,color=i) for i,role in enumerate(['train','train','calibration','calibration','test','test'])]
   rows += [self.row(base,'bird'+str(i),'bird','bird-recording'+str(i),role,color=10+i) for i,role in enumerate(['train','train','calibration','calibration','test','test'])]
   (base/'dataset.json').write_text(json.dumps(dict(fingerprint='base',samples=rows)))
   new=self.row(reviews,'review','cloud','new-recording',color=50)
   def manifest(fp): (reviews/'reviews.json').write_text(json.dumps(dict(fingerprint=fp,samples=[new])))
   manifest('first');one=build(base,reviews,root/'one',root/'ledger.json')
   assigned={r['origin']:r['split'] for r in one['samples']}
   for r in rows:self.assertEqual(assigned[r['origin']],r['split'])
   new['label']='bird';manifest('correction');two=build(base,reviews,root/'two',root/'ledger.json')
   corrected=next(r for r in two['samples'] if r['origin']=='review')
   self.assertEqual(corrected['label'],'bird');self.assertEqual(corrected['split'],assigned['review']);self.assertNotEqual(one['fingerprint'],two['fingerprint'])
 def test_changed_pixels_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);row=self.row(root,'review','cloud','group');row['pixel_sha256']='wrong'
   (root/'dataset.json').write_text(json.dumps(dict(fingerprint='base',samples=[])))
   (root/'reviews.json').write_text(json.dumps(dict(fingerprint='review',samples=[row])))
   with self.assertRaisesRegex(ValueError,'checksum'):build(root,root,root/'out',root/'ledger.json')

 def test_new_star_labels_are_retained_but_do_not_block_existing_classes(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);base=root/'base';reviews=root/'reviews';base.mkdir();reviews.mkdir()
   rows=[self.row(base,'b'+str(i),'cloud','recording'+str(i),role,color=i) for i,role in enumerate(['train','train','calibration','calibration','test','test'])]
   (base/'dataset.json').write_text(json.dumps(dict(fingerprint='base',samples=rows)))
   stars=[self.row(reviews,'s'+str(i),'star','star-recording'+str(i),color=100+i) for i in range(6)]
   (reviews/'reviews.json').write_text(json.dumps(dict(fingerprint='one-star',samples=stars[:1])))
   one=build(base,reviews,root/'one',root/'ledger.json')
   self.assertEqual(one['blockers'],[]);self.assertEqual(one['classes'],['cloud','star']);self.assertEqual(one['deferred'],[]);self.assertEqual(one['human_training_counts'],{'star':1});self.assertTrue(one['validation_limits']);self.assertTrue((reviews/'s0.png').exists())
   (reviews/'reviews.json').write_text(json.dumps(dict(fingerprint='six-stars',samples=stars)))
   enough=build(base,reviews,root/'enough',root/'ledger.json')
   self.assertEqual(enough['blockers'],[]);self.assertIn('star',enough['classes']);self.assertEqual(enough['deferred'],[])

 def test_every_review_trains_even_with_frozen_holdout_and_identical_pixels(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);base=root/'base';reviews=root/'reviews';base.mkdir();reviews.mkdir()
   rows=[self.row(base,'b'+str(i),'cloud','recording'+str(i),role,color=i) for i,role in enumerate(['train','train','calibration','calibration','test','test','test'])]
   (base/'dataset.json').write_text(json.dumps(dict(fingerprint='base',samples=rows)))
   confirmed=[self.row(reviews,'tree'+str(i),'tree','recording4',color=4 if i<2 else 100+i) for i in range(10)]
   (reviews/'reviews.json').write_text(json.dumps(dict(fingerprint='trees',samples=confirmed)))
   ledger=root/'ledger.json';ledger.write_text(json.dumps({'recording4':'test'}))
   result=build(base,reviews,root/'out',ledger)
   trained=[r for r in result['samples'] if r['human_confirmed']]
   self.assertEqual(len(trained),10);self.assertEqual({r['split'] for r in trained},{'train'})
   self.assertEqual(result['human_training_counts'],{'tree':10});self.assertEqual(result['deferred'],[])
   self.assertFalse(any(r['split']!='train' and r['pixel_sha256'] in {x['pixel_sha256'] for x in confirmed} for r in result['samples']))
   self.assertFalse(any(r['origin']=='b4' for r in result['samples']))
   for group in {r['group'] for r in result['samples']}:
    self.assertEqual(len({r['split'] for r in result['samples'] if r['group']==group}),1)
