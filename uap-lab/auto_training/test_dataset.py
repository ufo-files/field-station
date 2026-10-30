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
