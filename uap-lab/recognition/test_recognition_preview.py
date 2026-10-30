import tempfile,unittest
from pathlib import Path
import cv2,numpy as np
from recognition_preview import RecognitionPreview,unpack
class PreviewTests(unittest.TestCase):
 def test_same_frame_tags_and_pixels_are_one_atomic_derivative(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);image=np.zeros((720,1280,3),np.uint8);worker=RecognitionPreview(root);timing={'sequence':123,'pts_seconds':2.05,'received_epoch':100};objects=[{'suggested_label':'bird','box':[100,100,40,40],'proposed_track_id':'bird-1'},{'suggested_label':'cloud','box':[400,100,40,40],'proposed_track_id':'cloud-1'}]
   worker.submit(image,objects,timing,'run-test','model-test');worker.close();meta,jpeg=unpack((root/'preview.bin').read_bytes())
   self.assertEqual(meta['sequence'],123);self.assertEqual(meta['source_received_epoch'],100);self.assertEqual([o['label'] for o in meta['tags']],['bird']);self.assertTrue(meta['derivative']);self.assertFalse(meta['capture_control']);self.assertEqual(cv2.imdecode(np.frombuffer(jpeg,np.uint8),1).shape,image.shape);self.assertEqual(np.count_nonzero(image),0)
 def test_incomplete_bundle_is_rejected(self):
  for raw in (b'',b'\x00\x00\x00\x40broken'):
   with self.assertRaises(ValueError):unpack(raw)
