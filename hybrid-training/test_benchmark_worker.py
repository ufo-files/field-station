import unittest
from benchmark_worker import choose
class BenchmarkTests(unittest.TestCase):
 def test_random_sample_shared_manifest_reproducible_but_changes_between_runs(self):
  rows=[dict(origin=str(i),human_confirmed=True,label='anomalous' if i%2 else 'not_anomalous') for i in range(1000)]
  a,seed=choose(rows);b,_=choose(rows);repeat,_=choose(rows,seed=int(seed))
  self.assertEqual(a,repeat);self.assertNotEqual(a,b);self.assertEqual(len(a),500);self.assertEqual(len({r['origin'] for r in a}),500)
 def test_machine_labels_never_become_reference_truth(self):
  with self.assertRaises(ValueError):choose([dict(human_confirmed=False,label='anomalous')]*500)
