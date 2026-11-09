import json,tempfile,unittest
from pathlib import Path
from manual_recordings import listing

class ManualRecordingsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.data=self.root/'lab';self.station=self.root/'station'
  (self.data/'live').mkdir(parents=True);(self.station/'sessions').mkdir(parents=True)
  self.records=[]
 def add(self,sid,state='completed',playback='completed',origin='manual'):
  folder=self.station/'sessions'/sid;folder.mkdir()
  self.records.append(dict(session_id=sid,created=len(self.records)))
  (self.data/'live/manual-sessions.json').write_text(json.dumps(self.records))
  (folder/'manifest.json').write_text(json.dumps(dict(id=sid,state=state,capture_origin=origin,started_epoch=len(self.records),elapsed_seconds=12,video_playback={'state':playback})))
  if playback=='completed':(folder/'video.mp4').write_bytes(b'video')
  return folder
 def test_ready_preparing_active_are_all_listed_without_training_labels(self):
  self.add('20261109T055133Z-704e15')
  self.add('20261109T055847Z-dbe797',playback='processing')
  self.add('20261109T061521Z-5f76f6',state='recording',playback='queued')
  result=listing(self.data,self.station)
  self.assertEqual([r['state'] for r in result['items']],['recording','preparing','ready'])
  self.assertIsNone(result['items'][0]['video_url']);self.assertIsNone(result['items'][1]['video_url'])
  self.assertIn('video.mp4',result['items'][2]['video_url'])
  self.assertTrue(all(r['label'] is None and not r['human_reviewed'] for r in result['items']))
  self.assertFalse((self.data/'email-reviews').exists())
 def test_approval_and_verified_archive_only(self):
  sid='20261109T055133Z-704e15';folder=self.add(sid)
  (folder/'manual-archive-approval.json').write_text(json.dumps(dict(session_id=sid,human_confirmed=True,classification='anomalous',upload_requested=True)))
  receipt=folder/'manual-internet-archive.json'
  for state in ['uploading','verified']:
   receipt.write_text(json.dumps(dict(state=state,url='https://archive.org/details/test-recording')))
   row=listing(self.data,self.station)['items'][0]
   self.assertEqual(row['label'],'anomalous');self.assertTrue(row['human_reviewed'])
   self.assertEqual(bool(row['archive_url']),state=='verified')
 def test_cursor_and_nonmanual_exclusion(self):
  self.add('20261109T055133Z-704e15');self.add('20261109T055847Z-dbe797')
  self.add('20261109T061521Z-5f76f6',origin='provisional_motion')
  first=listing(self.data,self.station,limit=1)
  second=listing(self.data,self.station,before=first['next_cursor'],limit=1)
  self.assertEqual(first['total'],2);self.assertNotEqual(first['items'][0]['id'],second['items'][0]['id'])
  self.assertIsNone(second['next_cursor'])
 def test_removed_manifest_and_invalid_ids_are_not_links(self):
  self.records=[{'session_id':'../../secret'},{'session_id':'20261109T055133Z-704e15'}]
  (self.data/'live/manual-sessions.json').write_text(json.dumps(self.records))
  self.assertEqual(listing(self.data,self.station)['items'],[])
if __name__=='__main__':unittest.main()
