import hashlib,io,json,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from night_context_calibration import qualify,counts
class NightQualificationTests(unittest.TestCase):
 def exercise(self,lose_positive=False,changed_pixels=False):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);folder=root/'runs/run';folder.mkdir(parents=True)
   image=Image.new('RGB',(64,64));raw=io.BytesIO();image.save(raw,format='PNG');raw=raw.getvalue();pixel=hashlib.sha256(b'64x64:RGB:'+image.tobytes()).hexdigest()
   rows=[dict(id=str(i),label='anomalous' if i<20 else 'not_anomalous',generation=str(i%2)) for i in range(40)]
   with tarfile.open(root/'crop-parity-audit.tar','w') as tar:
    def add(name,data):
     info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
    add('samples.json',json.dumps(rows).encode())
    for row in rows:
     for kind in ['tight','context']:add(row['id']+'-'+kind+'.png',raw)
   dataset=dict(fingerprint='new',samples=[dict(origin='email:'+r['id'],label=r['label'],human_confirmed=True,pixel_sha256='changed' if changed_pixels else pixel) for r in rows])
   worker=Mock();worker.predict.side_effect=[[dict(scores={'anomalous':.9}) for _ in rows],[dict(scores={'anomalous':.9 if i<20 and not(lose_positive and i==0) else 0}) for i in range(40)]]
   return qualify(folder,dataset,worker,.85)
 def test_requires_reduction_without_positive_loss(self):
  self.assertTrue(self.exercise()['enabled']);self.assertFalse(self.exercise(lose_positive=True)['enabled'])
 def test_stale_pixels_cannot_qualify(self):self.assertFalse(self.exercise(changed_pixels=True)['enabled'])
 def test_invalid_or_missing_scores_fail(self):
  with self.assertRaises(ValueError):counts([{'label':'anomalous'}],[.9],[float('nan')],.85)
  with self.assertRaises(ValueError):counts([{'label':'anomalous'}],[],[],.85)
