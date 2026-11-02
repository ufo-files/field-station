import base64,json,threading,unittest
from unittest.mock import patch
from types import SimpleNamespace
from crop_client import CropClassifier,CropWorkerError
class CropBatchTests(unittest.TestCase):
 def worker(self):
  worker=CropClassifier.__new__(CropClassifier);worker.version='test';worker.lock=threading.Lock();sent=[]
  class Input:
   def write(self,text):sent.append(json.loads(text))
   def flush(self):pass
  worker.proc=SimpleNamespace(stdin=Input())
  worker.receive=lambda:dict(id=sent[-1]['id'],version='test',results=[dict(index=i) for i in range(len(sent[-1]['images']))])
  return worker,sent
 def test_large_images_split_by_encoded_bytes_without_changing_pixels_or_order(self):
  worker,sent=self.worker();images=[bytes([i])*300 for i in range(7)]
  with patch('crop_client.MAX_REQUEST_BYTES',1000):result=worker.predict(images,request_id='batch')
  self.assertEqual([r['index'] for r in result],list(range(7)))
  self.assertEqual([base64.b64decode(v) for request in sent for v in request['images']],images)
  self.assertGreater(len(sent),1)
  self.assertTrue(all(len(json.dumps(request).encode())<=1000 for request in sent))
 def test_count_limit_still_applies_to_small_crops(self):
  worker,sent=self.worker();worker.predict([b'x']*600)
  self.assertEqual([len(r['images']) for r in sent],[256,256,88])
 def test_oversized_single_crop_fails_before_writing(self):
  worker,sent=self.worker()
  with patch('crop_client.MAX_REQUEST_BYTES',100),self.assertRaises(CropWorkerError):worker.predict([b'x'*100])
  self.assertEqual(sent,[])
