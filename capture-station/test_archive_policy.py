import time
from unittest import TestCase
from unittest.mock import patch
from archive_policy import eligible
from test_internet_archive import ArchiveTests,SID
from experiments import save
class PolicyTests(TestCase):
 def test_only_manual_or_confirmed_anomaly(self):
  self.assertFalse(eligible({'capture_origin':'manual','provisional':True}))
  self.assertFalse(eligible({'capture_origin':'provisional_motion','classification_state':'pending'}))
  self.assertFalse(eligible({'capture_origin':'motion_trigger'}));self.assertFalse(eligible({}))
  self.assertFalse(eligible({'capture_origin':'manual','validation':True}))
  m={'id':SID,'capture_origin':'provisional_motion'};d={'schema':2,'source':'station_web_ui','bundle_ready':True,'videos':['video.mp4','video-annotated.mp4'],'session_id':SID,'human_confirmed':True,'confirmed_anomalous':True,'reviewed_epoch':time.time()}
  self.assertTrue(eligible(m,d));d['human_confirmed']=False;self.assertFalse(eligible(m,d))
class QueuePolicyTests(TestCase):
 def setUp(self):
  ArchiveTests.setUp(self)
  (self.folder/'archive-decision.json').unlink()
 tearDown=ArchiveTests.tearDown
 def test_existing_upload_is_held_without_deleting_local_or_resume_state(self):
  self.job.update(state='uploading',upload_id='existing',parts=[{'bytes':8,'number':1,'etag':'x'}]);self.m.update(capture_origin='provisional_motion',provisional=True);save(self.folder/'manifest.json',self.m)
  self.a.reconcile_policy();self.assertEqual(self.job['state'],'held_for_review');self.assertEqual(self.job['upload_id'],'existing');self.assertEqual(self.job['policy_previous_state'],'uploading')
  self.a.send(self.job);self.assertFalse(self.api.calls);self.assertTrue((self.folder/'video.mkv').exists())
 def test_confirmed_human_review_resumes_existing_job(self):
  self.m.update(capture_origin='provisional_motion',provisional=True);save(self.folder/'manifest.json',self.m);self.a.reconcile_policy()
  save(self.folder/'archive-decision.json',self.decision)
  self.a.reconcile_policy();current=self.a.job_cache[SID];self.assertEqual(current['state'],'queued');self.assertIn('archive-decision.json',[e['name'] for e in current['files']])
 def test_unconfirmed_session_not_discovered(self):
  self.a.job_cache.clear();self.m.update(capture_origin='provisional_motion',provisional=True);save(self.folder/'manifest.json',self.m);self.a.discover();self.assertFalse(self.a.job_cache)
 def test_negative_review_remains_local(self):
  self.m.update(capture_origin='provisional_motion',provisional=True);save(self.folder/'manifest.json',self.m)
  save(self.folder/'archive-decision.json',dict(schema=1,session_id=SID,human_confirmed=True,confirmed_anomalous=False,reviewed_epoch=time.time()))
  self.a.reconcile_policy();self.assertEqual(self.job['state'],'held_for_review')
