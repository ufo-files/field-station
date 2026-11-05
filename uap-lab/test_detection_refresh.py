import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import detection_library as library
class RefreshTests(unittest.TestCase):
 def test_rebuild_keeps_complete_cache_until_atomic_replacement(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);old=[{'id':'old'}];new=[{'id':'new'}];entered=threading.Event();release=threading.Event()
   library._CACHE[str(root)]=(0,old)
   def build(data,publish):
    publish([]);entered.set();release.wait(5);return new
   try:
    with patch.object(library,'collect',side_effect=build):
     cached,busy,error=library.refresh(root)
     self.assertTrue(busy);self.assertTrue(entered.wait(2))
     self.assertEqual(library._CACHE[str(root)][1],old)
     done=library._BUILDING[str(root)];release.set();self.assertTrue(done.wait(2))
     self.assertEqual(library.refresh(root)[0][1],new)
   finally:release.set();library.invalidate()

 def test_cache_persistence_does_not_block_interactive_lock(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);entered=threading.Event();release=threading.Event();original=Path.write_text
   def write(path,*args,**kwargs):
    if path.suffix=='.tmp':entered.set();release.wait(5)
    return original(path,*args,**kwargs)
   try:
    with patch.object(library,'collect',return_value=[]),patch.object(Path,'write_text',write):
     library.refresh(root);self.assertTrue(entered.wait(2))
     acquired=library._LOCK.acquire(timeout=.2)
     try:self.assertTrue(acquired)
     finally:
      if acquired:library._LOCK.release()
     done=library._BUILDING[str(root)];release.set();self.assertTrue(done.wait(2))
   finally:release.set();library.invalidate()

 def test_arrival_is_visible_while_historical_refresh_is_blocked(self):
  import json,time
  from recognition.recognition_alerts import record_arrivals,publish_notice,notice_path
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);data=root/'uap-lab';data.mkdir();out=root/'notifications/outbox';out.mkdir(parents=True)
   (data/'review-queue-cleared.json').write_text(json.dumps(dict(cutoff_epoch=10)))
   event=dict(id='a'*32,created_epoch=11,classification='anomalous')
   record_arrivals(out,[],complete_since=10);publish_notice(out,event)
   self.assertEqual(json.loads(notice_path(out).read_text())['id'],event['id'])
   entered=threading.Event();release=threading.Event();library._CACHE[str(data)]=(0,[])
   def blocked(*args):entered.set();release.wait(5);return []
   try:
    with patch.object(library,'collect',side_effect=blocked):
     result=library.listing(data,'needs_review');self.assertTrue(entered.wait(2))
     self.assertEqual([r['id'] for r in result['items']],[event['id']]);self.assertFalse(result['indexing']);self.assertTrue(result['ready'])
     (data/'review-queue-cleared.json').write_text(json.dumps(dict(cutoff_epoch=12)))
     self.assertEqual(library.listing(data,'needs_review')['items'],[])
     done=library._BUILDING[str(data)];release.set();self.assertTrue(done.wait(2))
   finally:release.set();library.invalidate()
