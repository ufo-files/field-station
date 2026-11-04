import tempfile,unittest
from pathlib import Path
from model_tests import request,save,state,pending,update
class ModelTestQueue(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name);self.model='a'*64
  save(self.data/'model-tests/catalog.json',dict(models=[dict(id=self.model)],benchmark=dict(id='sample',count=500)))
 def tearDown(self):self.temp.cleanup()
 def test_double_click_is_one_job_and_result_is_retained(self):
  one=request(self.data,self.model,'sample');self.assertEqual(request(self.data,self.model,'sample'),one)
  self.assertEqual(len(pending(self.data)),1)
  update(self.data,dict(one,state='complete',result=dict(correct=495,total=500)))
  self.assertEqual(state(self.data)['models'][0]['test']['result']['correct'],495)
  two=request(self.data,self.model,'sample');self.assertNotEqual(one['id'],two['id'])
  with self.assertRaises(ValueError):update(self.data,dict(one,state='failed'))
 def test_reject_unknown_model_and_different_sample(self):
  for model,sample in [('../escape','sample'),('b'*64,'sample'),(self.model,'wrong')]:
   with self.assertRaises(ValueError):request(self.data,model,sample)
  self.assertEqual(pending(self.data),[])
