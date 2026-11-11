import tempfile,unittest,json
from pathlib import Path
from store import Store
from sync import Sync

def row(key='a',label='anomalous'):
 return dict(id=key,label=label,human_reviewed=False,review_revision='unreviewed',created=1,image_url='/api/label-queue/image?id='+key,frame_url='/api/label-queue/image?full=1&id='+key)
class StorageTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Store(self.temp.name,limit=10)
 def test_offline_save_survives_restart_and_retries_same_id(self):
  s=self.store;s.ingest([row()]);s.cache('a','crop',b'frame');request=s.queue(['a'],'not_anomalous','Alice')[0]
  s=Store(self.temp.name,10);self.assertTrue(s.rows()[0]['human_reviewed']);self.assertEqual(s.rows()[0]['label'],'not_anomalous')
  first=s.outgoing();s.results(first,[]);self.assertEqual(s.outgoing()[0]['request_id'],request)
 def test_pending_frame_survives_budget_and_snapshot_removal(self):
  s=self.store;s.ingest([row('a'),row('b')]);s.cache('a','crop',b'12345678');s.queue(['a'],'not_anomalous','A')
  self.assertFalse(s.cache('b','crop',b'12345'));s.ingest([],complete=True)
  self.assertEqual(s.image('a','crop').read_bytes(),b'12345678');self.assertEqual(len(s.rows()),1)
 def test_synced_cache_can_be_reclaimed_without_deleting_decision(self):
  s=self.store;s.ingest([row('a'),row('b')]);s.cache('a','crop',b'12345678');s.queue(['a'],'not_anomalous','A');items=s.outgoing()
  s.results(items,[dict(request_id=items[0]['request_id'],state='synced',review_revision='new')]);self.assertTrue(s.cache('b','crop',b'12345'));self.assertLessEqual(s.summary()['cache_bytes'],10);self.assertEqual(s.summary()['decisions']['synced'],1)
 def test_conflict_is_preserved_until_explicit_resolution(self):
  s=self.store;s.ingest([row()]);s.cache('a','crop',b'frame');request=s.queue(['a'],'not_anomalous','A')[0];items=s.outgoing()
  s.results(items,[dict(request_id=request,state='conflict',current_revision='changed',current_label='anomalous')]);self.assertEqual(s.outgoing(),[])
  s.resolve(request,'retry');item=s.outgoing()[0];self.assertEqual(item['base_revision'],'changed');self.assertNotEqual(item['request_id'],request)
 def test_online_snapshot_cannot_hide_unsynced_decision(self):
  s=self.store;s.ingest([row()]);s.cache('a','crop',b'frame');s.queue(['a'],'not_anomalous','A');s.ingest([row()]);self.assertEqual(s.rows()[0]['label'],'not_anomalous')
 def test_partial_snapshot_does_not_remove_frames(self):
  s=self.store;s.ingest([row()]);s.cache('a','crop',b'frame');s.ingest([],complete=False);self.assertEqual(len(s.rows()),1)
 def test_sync_does_not_download_video_urls(self):
  s=self.store;r=row();r.update(image_url='/api/email-review/video?id=a',frame_url='/api/session/video?id=a');calls=[]
  worker=Sync(s,'http://field')
  def request(path,body=None,token=None):
   calls.append(path)
   if path.endswith('/token'):return json.dumps(dict(token='x')).encode(),'application/json'
   if path=='/api/hq/snapshot':return json.dumps(dict(schema=1,complete=True,items=[r])).encode(),'application/json'
   raise AssertionError(path)
  worker.request=request;worker.cycle();self.assertEqual(len(calls),2);self.assertEqual(s.summary()['cache_bytes'],0)
 def test_lower_priority_frame_cannot_evict_current_working_set(self):
  s=self.store;s.ingest([row('a'),row('b')]);s.cache('a','crop',b'12345678')
  self.assertFalse(s.cache('b','crop',b'12345',{'a','b'}));self.assertEqual(s.image('a','crop').read_bytes(),b'12345678')
 def test_changed_field_review_refreshes_stale_cached_image(self):
  s=self.store;s.ingest([row()]);s.cache('a','crop',b'frame',version='unreviewed');changed=row();changed['review_revision']='new';s.ingest([changed]);self.assertFalse(s.rows()[0]['cached'])
 def test_offline_cycle_keeps_local_data(self):
  s=self.store;s.ingest([row()]);s.cache('a','crop',b'frame');s.queue(['a'],'not_anomalous','A');worker=Sync(s,'http://field');worker.request=lambda *args:(_ for _ in ()).throw(OSError('offline'));worker.cycle();self.assertFalse(s.summary()['sync']['online']);self.assertEqual(s.summary()['decisions']['pending'],1)
if __name__=='__main__':unittest.main()
