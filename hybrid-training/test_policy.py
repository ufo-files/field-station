import unittest
from policy import pseudo_label,eligible_pseudo,score
class HybridPolicyTests(unittest.TestCase):
 def test_confidence_and_consistency_are_both_required(self):
  good={'anomalous':.999,'not_anomalous':.001};bad={'anomalous':.001,'not_anomalous':.999}
  self.assertEqual(pseudo_label([good]*3),'anomalous');self.assertIsNone(pseudo_label([good,good,bad]));self.assertIsNone(pseudo_label([good]*2));self.assertIsNone(pseudo_label([{'anomalous':.8,'not_anomalous':.2}]*3))
 def test_humans_override_id_and_identical_pixels_even_with_opposite_label(self):
  human=[dict(origin='email:one',pixel_sha256='human',label='not_anomalous')]
  pseudo=[dict(id=k,pixel_sha256=p,label='anomalous') for k,p in [('one','other'),('two','human'),('three','new'),('four','new')]]
  self.assertEqual([r['id'] for r in eligible_pseudo(human,pseudo)],['three'])
 def test_unreviewed_and_training_replays_do_not_inflate_metrics(self):
  rows=[dict(prospective=True,truth='not_anomalous',human='anomalous',hybrid='not_anomalous',generation='one'),dict(prospective=False,truth='anomalous',human='anomalous',hybrid='anomalous',generation='two')]
  result=score(rows);self.assertEqual(result['lanes']['human']['fp'],1);self.assertEqual(result['lanes']['hybrid']['tn'],1);self.assertEqual(result['recordings'],1);self.assertFalse(result['automatic_switch'])
