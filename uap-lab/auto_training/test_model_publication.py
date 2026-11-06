import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import model_publication as pub
class FakeGitHub:
 def __init__(self):self.release=None;self.assets={};self.creates=0;self.uploads=[];self.fail=None;self.corrupt=False
 def find(self,tag):return None if self.release is None else dict(self.release,assets=[dict(name=n) for n in self.assets])
 def create(self,tag,notes):self.creates+=1;self.release=dict(draft=True,html_url='https://github.com/example/models/releases/tag/'+tag)
 def upload(self,tag,path):
  if self.fail==path.name:self.fail=None;raise OSError('network interrupted')
  self.assets[path.name]=path.read_bytes();self.uploads.append(path.name)
 def download(self,tag,name,directory):Path(directory,name).write_bytes(b'corrupt' if self.corrupt else self.assets[name])
 def publish(self,tag):self.release['draft']=False
class PublicationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.folder=self.root/'run';self.folder.mkdir();self.version='a'*64;self.config=dict(root=str(self.root),model_publication=dict(enabled=True,repository='example/models'));self.release=dict(version=self.version,previous_version='b'*64,deployed_epoch=123)
  (self.folder/'candidate.mlpackage').mkdir();(self.folder/'candidate.mlpackage/model.bin').write_bytes(b'model');(self.folder/'candidate-weights.pt').write_bytes(b'weights')
  pub.save(self.folder/'candidate-policy.json',dict(version=self.version,classes=['anomalous','not_anomalous'],thresholds={'anomalous':.8},private_path='/secret/private',credentials='not public'))
  pub.save(self.folder/'promotion-evaluation.json',dict(passed=True,candidate_version=self.version,baseline_version='b'*64,baseline=dict(total=10,predictions=['private']),candidate=dict(total=10,predictions=['private'])))
  self.github=FakeGitHub()
 def tearDown(self):self.tmp.cleanup()
 def job(self):return pub.enqueue(self.config,self.folder,self.release)
 def run_tick(self):return pub.tick(self.config,lambda repo:self.github)
 def test_deployed_only_idempotence_and_downloaded_verification(self):
  self.job();self.job();result=self.run_tick();self.assertEqual(result['state'],'published');self.assertEqual(self.github.creates,1);self.assertFalse(self.github.release['draft']);self.assertEqual(len(self.github.uploads),4)
  self.assertIsNone(self.run_tick());self.assertEqual(len(self.github.uploads),4)
  root=self.root/'model-publication';self.assertTrue((root/'receipts'/(self.version+'.json')).exists())
  import tarfile
  with tarfile.open(root/'artifacts'/self.version/'model.tar.gz') as archive:
   policy=json.load(archive.extractfile('candidate-policy.json'));self.assertNotIn('credentials',policy);self.assertNotIn('private_path',policy)
   evaluation=json.load(archive.extractfile('evaluation.json'));self.assertNotIn('predictions',evaluation['candidate']);self.assertIn('SHA256SUMS',archive.getnames())
 def test_badge_counts_reviewed_crops_and_is_checksummed(self):
  pub.save(self.folder/'dataset.json',dict(human_training_counts={'anomalous':307,'not_anomalous':30702},samples=['private']))
  self.job();self.assertEqual(self.run_tick()['state'],'published')
  badge=self.github.assets['labels-badge.json'];self.assertEqual(json.loads(badge)['message'],'31,009')
  self.assertNotIn(b'private',badge)
  self.assertIn(hashlib.sha256(badge).hexdigest()+'  labels-badge.json',self.github.assets['SHA256SUMS'].decode())
 def test_missing_counts_are_not_reported_as_zero(self):
  self.assertEqual(pub.labels_badge(self.folder)['message'],'not recorded')
 def test_manual_release_keeps_failed_validation_in_published_bundle(self):
  report=pub.read(self.folder/'promotion-evaluation.json');report.update(passed=False,reasons=['Recall regressed'],manual_deployment=dict(request_id='manual-1',runtime_validated=True));pub.save(self.folder/'promotion-evaluation.json',report)
  self.job();self.assertEqual(self.run_tick()['state'],'published')
  import tarfile
  with tarfile.open(self.root/'model-publication/artifacts'/self.version/'model.tar.gz') as archive:
   evaluation=json.load(archive.extractfile('evaluation.json'));self.assertFalse(evaluation['passed']);self.assertEqual(evaluation['reasons'],['Recall regressed'])
   card=json.load(archive.extractfile('model-card.json'));self.assertIn('did not meet automatic promotion rules',card['validation'])
 def test_network_retry_keeps_draft_and_reuses_assets(self):
  self.job();self.github.fail='model-card.json';result=self.run_tick();self.assertEqual(result['state'],'retrying');self.assertTrue(self.github.release['draft'])
  path=self.root/'model-publication/outbox'/(self.version+'.json');result['next_attempt']=0;pub.save(path,result);result=self.run_tick();self.assertEqual(result['state'],'published');self.assertEqual(self.github.uploads.count('model.tar.gz'),1);self.assertEqual(self.github.creates,1)
 def test_corrupt_remote_asset_never_published(self):
  self.job();self.github.corrupt=True;result=self.run_tick();self.assertEqual(result['state'],'retrying');self.assertIn('checksum mismatch',result['error']);self.assertTrue(self.github.release['draft']);self.assertFalse((self.root/'model-publication/receipts'/(self.version+'.json')).exists())
 def test_rejected_or_unproven_model_not_enqueued(self):
  report=pub.read(self.folder/'promotion-evaluation.json');report['passed']=False;pub.save(self.folder/'promotion-evaluation.json',report)
  with self.assertRaises(ValueError):self.job()
  report['passed']=True;pub.save(self.folder/'promotion-evaluation.json',report);self.release.pop('deployed_epoch')
  with self.assertRaises(ValueError):self.job()
 def test_bundle_tampering_fails_retry(self):
  job=self.job();root=self.root/'model-publication';folder,_=pub.bundle(root,job);(folder/'model.tar.gz').write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'bundle changed'):pub.bundle(root,job)
 def test_disabled_publisher_does_not_queue(self):
  self.config['model_publication']['enabled']=False;self.assertIsNone(self.job());self.assertIsNone(self.run_tick())
 def test_release_handoff_is_queued_before_pending_is_cleared(self):
  from controller import Controller
  from unittest.mock import Mock
  cfg=dict(self.config,remote_app='/app',remote_python='python',host='station',capacity_retention=True);controller=Controller(cfg);controller.state=dict(phase='deployed',remote_candidate='/candidate',run_directory=str(self.folder),pending_release=self.release);controller.rpc=Mock(return_value={'queued':True})
  controller.notify_release();self.assertIsNone(controller.state['pending_release']);self.assertEqual(pub.read(self.root/'model-publication/outbox'/(self.version+'.json'))['state'],'queued')
 def test_enqueue_failure_keeps_release_pending(self):
  from controller import Controller
  from unittest.mock import Mock
  controller=Controller(dict(self.config,remote_app='/app',remote_python='python',host='station',capacity_retention=True));controller.state=dict(phase='deployed',remote_candidate='/candidate',run_directory=str(self.folder),pending_release=self.release);controller.rpc=Mock(return_value={'queued':True})
  with patch('model_publication.enqueue',side_effect=OSError('disk full')),self.assertRaises(OSError):controller.notify_release()
  self.assertEqual(controller.state['pending_release'],self.release)

class DraftLookupTests(unittest.TestCase):
 def test_draft_found_in_paginated_releases_after_tag_404(self):
  github=pub.GitHub('example/models');draft=dict(tag_name='model-x',draft=True,assets=[])
  with patch.object(github,'run',side_effect=[RuntimeError('HTTP 404'),json.dumps([[],[draft]])]) as run:
   self.assertEqual(github.find('model-x'),draft);self.assertIn('--paginate',run.call_args.args[0])
 def test_authentication_failure_not_mistaken_for_missing_release(self):
  github=pub.GitHub('example/models')
  with patch.object(github,'run',side_effect=RuntimeError('HTTP 401')),self.assertRaisesRegex(RuntimeError,'401'):github.find('model-x')
