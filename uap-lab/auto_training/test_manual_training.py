import tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from manual_training import Control
class ManualTrainingTests(unittest.TestCase):
 def test_concurrent_requests_are_idempotent_and_survive_restart(self):
  with tempfile.TemporaryDirectory() as root:
   with ThreadPoolExecutor(max_workers=8) as pool:
    states=list(pool.map(lambda _:Control(root).request(),range(20)))
   self.assertEqual(len({s['request_id'] for s in states}),1)
   c=Control(root);request=c.claim();self.assertEqual(c.claim()['id'],request['id'])
   c.progress({'phase':'training'});self.assertTrue(c.status()['busy'])
   c.finish(request['id'],{'phase':'rejected'});self.assertFalse(c.status()['busy'])
   self.assertNotEqual(c.request()['request_id'],request['id'])
 def test_scheduled_training_blocks_duplicate_request(self):
  with tempfile.TemporaryDirectory() as root:
   c=Control(root);c.progress({'phase':'refining_class_corrections'})
   self.assertTrue(c.request()['busy']);self.assertEqual(c.claim(),{})
   c.progress({'phase':'deployed'});self.assertEqual(c.request()['phase'],'queued')
 def test_wrong_request_cannot_complete_active_training(self):
  with tempfile.TemporaryDirectory() as root:
   c=Control(root);c.request()
   with self.assertRaises(ValueError):c.finish('wrong',{'phase':'deployed'})
   self.assertTrue(c.status()['busy'])
