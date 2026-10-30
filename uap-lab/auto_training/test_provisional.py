import json,tempfile,unittest
from pathlib import Path
from provisional import slot,compact_evaluation
from provisional_station import expire_alerts
class ProvisionalTests(unittest.TestCase):
 def test_schedule_starts_expires_and_crosses_hour_once(self):
  cfg={'provisional':dict(enabled=True,start_epoch=100,end_epoch=100+30*86400)}
  self.assertIsNone(slot(cfg,99));self.assertEqual(slot(cfg,100),0);self.assertEqual(slot(cfg,3699),0);self.assertEqual(slot(cfg,3700),1);self.assertIsNone(slot(cfg,100+30*86400))
 def test_queue_cleanup_preserves_inflight_sent_uncertain_and_future(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for i,state in enumerate(('pending','accepted_by_mail','submitting','uncertain','cancelled','suppressed','expired','future')):
    f=root/str(i);f.mkdir();(f/'event.json').write_text(json.dumps(dict(created_epoch=101 if state=='future' else 10)))
    if state not in ('pending','future'):(f/'delivery.json').write_text(json.dumps(dict(state=state)))
    (f/'native.png').write_bytes(b'training')
   self.assertEqual(expire_alerts(root,100),1);self.assertEqual(expire_alerts(root,100),0)
   self.assertEqual(len(list(root.glob('*/native.png'))),8);self.assertFalse((root/'7/delivery.json').exists())
   for i,state in ((1,'accepted_by_mail'),(2,'submitting'),(3,'uncertain')):self.assertEqual(json.loads((root/str(i)/'delivery.json').read_text())['state'],state)
 def test_reports_keep_denominators_without_training_fit_claims(self):
  result=compact_evaluation(dict(passed=True,candidate=dict(per_class={'cloud':dict(tp=4,fn=6)},total=10,predictions=['large']),reviewed_corrections={'training_only':True}))
  self.assertEqual(result['candidate']['total'],10);self.assertNotIn('predictions',result['candidate']);self.assertNotIn('reviewed_corrections',result)

 def test_additions_do_not_starve_hourly_release_but_corrections_do(self):
  from provisional import compatible_reviews
  old=[dict(origin='a',label='cloud',pixel_sha256='pixels',group='g')]
  self.assertTrue(compatible_reviews(old,old+[dict(origin='b',label='bird',pixel_sha256='other',group='h')]))
  self.assertFalse(compatible_reviews(old,[]))
  self.assertFalse(compatible_reviews(old,[dict(old[0],label='bird')]))
  self.assertFalse(compatible_reviews(old,old+[dict(old[0],origin='b',label='bird')]))
