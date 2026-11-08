import json,tempfile,unittest,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from archive_withdrawal import correction,reconcile
class WithdrawalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.folder=self.root/'sessions'/'20261108T010000Z-abcdef';self.folder.mkdir(parents=True);self.data=self.root/'uap-lab';self.data.mkdir()
  self.save(self.folder/'manifest.json',dict(spool_generation='g'))
  self.save(self.folder/'buffer-state.json',dict(segments=[dict(start=10,end=20)]))
  self.save(self.folder/'review-annotations.json',dict(annotations=[dict(label='anomalous',review_id='event',annotation_id='sample')]))
  self.rows=[dict(source='station_web_review',human_confirmed=True,event_id='event',sample_id='sample',label='not_anomalous',generation='g',pts_seconds=12,reviewed_epoch=20)]
 def save(self,path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
 def archive(self):
  self.save(self.data/'email-reviews/training-manifest.json',dict(examples=self.rows))
  self.job=dict(id=self.folder.name,identifier='owned-item',state='cleaned',verified_at=1)
  api=SimpleNamespace(visibility=Mock(return_value=42),metadata=Mock(return_value={'is_dark':True}))
  return SimpleNamespace(data=self.root/'sessions',job_cache={self.job['id']:self.job},folder=lambda _:self.folder,api=api,persist=Mock(),publish=Mock(),archive_eligible=Mock(return_value=False),complete_session_plan=Mock())
 def test_explicit_correction_is_proven(self):self.assertIsNotNone(correction(self.folder,self.data,self.rows))
 def test_missing_review_does_not_authorize_withdrawal(self):self.assertIsNone(correction(self.folder,self.data,[]))
 def test_deleted_or_machine_label_does_not_authorize(self):
  for change in [dict(deleted=True),dict(human_confirmed=False),dict(label='anomalous')]:self.assertIsNone(correction(self.folder,self.data,[dict(self.rows[0],**change)]))
 def test_any_remaining_anomaly_keeps_mixed_bundle(self):
  self.rows.append(dict(self.rows[0],sample_id='other',label='anomalous'));self.assertIsNone(correction(self.folder,self.data,self.rows))
 def test_unrelated_anomaly_does_not_block(self):
  self.rows.append(dict(self.rows[0],sample_id='other',label='anomalous',generation='elsewhere'));self.assertIsNotNone(correction(self.folder,self.data,self.rows))
 def test_cleaned_bundle_withdrawal_waits_for_confirmation(self):
  a=self.archive();reconcile(a);self.assertEqual(self.job['state'],'withdrawing');a.api.visibility.assert_called_once();self.assertFalse(a.api.metadata.called)
  self.job['withdrawal']['retry_epoch']=0;reconcile(a);self.assertEqual(self.job['state'],'withdrawn');self.assertTrue((self.data/'email-reviews/training-manifest.json').exists())
 def test_request_error_is_retried_without_claiming_success(self):
  a=self.archive();a.api.visibility.side_effect=OSError('offline');reconcile(a);self.assertEqual(self.job['state'],'withdrawing');self.assertIn('offline',self.job['error']);self.assertGreater(self.job['withdrawal']['retry_epoch'],time.time())
 def test_pending_export_alone_never_withdraws(self):
  a=self.archive();self.rows[0]['label']='anomalous';self.save(self.data/'email-reviews/training-manifest.json',dict(examples=self.rows));reconcile(a);a.api.visibility.assert_not_called()
 def test_reapproved_item_is_restored_only_after_export(self):
  a=self.archive();reconcile(a);self.job['withdrawal']['retry_epoch']=0;reconcile(a)
  self.rows[0]['label']='anomalous';self.save(self.data/'email-reviews/training-manifest.json',dict(examples=self.rows));self.job['withdrawal']['retry_epoch']=0
  reconcile(a);self.assertEqual(a.api.visibility.call_count,1)
  a.archive_eligible.return_value=True;reconcile(a);self.assertFalse(a.api.visibility.call_args.args[1])
  self.job['withdrawal']['retry_epoch']=0;a.api.metadata.return_value={'metadata':{'identifier':'owned-item'}};reconcile(a);self.assertEqual(self.job['state'],'queued');self.assertNotIn('withdrawal',self.job)
