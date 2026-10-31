import tempfile,unittest
from pathlib import Path
from mail_alerts import read,save
from release_backlog import clear,cancel_if_obsolete
class BacklogTests(unittest.TestCase):
 def test_success_cancels_only_unsent_older_models_and_keeps_evidence(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'outbox';root.mkdir();cfg={'outbox':str(root)}
   release=dict(version='new',deployed_epoch=100,state='deployed',health_verified=True)
   save(root.parent/'active-model-release.json',release)
   cases={'old':('old',90,None),'current':('new',90,None),'later':('candidate',110,None),'sent':('old',90,'accepted_by_mail'),'inflight':('old',90,'submitting'),'uncertain':('old',90,'uncertain')}
   for name,(model,epoch,state) in cases.items():
    folder=root/name;folder.mkdir();save(folder/'event.json',dict(model=model,created_epoch=epoch));(folder/'native-object.png').write_bytes(b'evidence')
    if state:save(folder/'delivery.json',dict(state=state))
   clear(cfg);clear(cfg)
   self.assertEqual(read(root/'old/delivery.json',{})['state'],'cancelled')
   for name,(_,_,state) in cases.items():
    self.assertEqual((root/name/'native-object.png').read_bytes(),b'evidence')
    if name!='old':self.assertEqual(read(root/name/'delivery.json',{}).get('state'),state)
   self.assertEqual(read(root.parent/'model-releases/new/backlog-cleanup.json',{})['cancelled_alerts'],1)
 def test_failed_or_unverified_release_does_not_clear(self):
  with tempfile.TemporaryDirectory() as tmp:
   for release in [dict(state='rejected',health_verified=True),dict(state='deployed',health_verified=False)]:
    self.assertIsNone(cancel_if_obsolete(Path(tmp),dict(model='old'),release))
 def test_late_old_publication_is_checked_even_after_bulk_cleanup(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);release=dict(state='deployed',health_verified=True,version='new',deployed_epoch=100)
   self.assertEqual(cancel_if_obsolete(folder,dict(model='old',created_epoch=99),release)['state'],'cancelled')

 def test_release_preserves_recent_candidates_unless_manual_clear_requested(self):
  import time
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);now=time.time();release=dict(state='deployed',health_verified=True,version='new',deployed_epoch=now)
   event=dict(model='old',created_epoch=now-47*3600)
   self.assertIsNone(cancel_if_obsolete(folder,event,release))
   self.assertEqual(cancel_if_obsolete(folder,event,dict(release,clear_candidate_backlog=True))['state'],'cancelled')
