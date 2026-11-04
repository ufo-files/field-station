import hashlib,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from email_training import reviewed_examples
from snapshot import collect
class SnapshotIntegrityTests(unittest.TestCase):
 def test_parallel_preparation_preserves_sample_identity_and_detects_corruption(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'videos').mkdir()
   for i in range(8):
    key=f'{i:032x}';folder=root/'email-reviews/examples'/key;folder.mkdir(parents=True)
    stream=io.BytesIO();Image.new('RGB',(12,9),(i,20,30)).save(stream,format='PNG');raw=stream.getvalue();(folder/'native-object.png').write_bytes(raw)
    (folder/'review.json').write_text(json.dumps(dict(event_id=key,label='anomalous',human_confirmed=True,generation='run-test',native_crop_sha256=hashlib.sha256(raw).hexdigest())))
   serial=reviewed_examples(root,prepared=True);parallel=reviewed_examples(root,workers=4,prepared=True)
   self.assertEqual(serial,parallel)
   before,images=collect(root);after,again=collect(root);self.assertEqual(before,after);self.assertEqual(images,again);self.assertEqual(len(images),8)
   (folder/'native-object.png').write_bytes(b'corrupted')
   with self.assertRaisesRegex(ValueError,'integrity'):collect(root)
