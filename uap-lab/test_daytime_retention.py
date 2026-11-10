import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from daytime_retention import eligible
from observation_metrics import TZ,daylight
from station_settings import settings,update
from retired_data import save
from review_retention import cycle

class DaytimePolicyTests(unittest.TestCase):
 def setUp(self):
  self.rise,self.set=daylight(datetime(2026,11,9).date());self.now=self.rise+5*3600
  self.event=dict(classification='not_anomalous',detected_epoch=self.rise+1)
 def test_age_and_sun_boundaries(self):
  policy=dict(enabled=True,after_seconds=10800)
  self.assertFalse(eligible(self.event,self.event['detected_epoch']+10799,policy))
  self.assertTrue(eligible(self.event,self.event['detected_epoch']+10800,policy))
  self.assertFalse(eligible(self.event,self.set,policy))
  self.assertFalse(eligible(dict(self.event,detected_epoch=self.rise-1),self.now,policy))
  self.assertTrue(eligible(dict(self.event,detected_epoch=self.rise),self.now,policy))
 def test_unknown_manual_starred_positive_and_disabled_are_preserved(self):
  for event in [dict(self.event,detected_epoch=None),dict(self.event,detected_epoch=float('nan')),dict(self.event,detected_epoch=True),dict(self.event,classification='anomalous'),dict(self.event,manual_session_id='manual'),dict(self.event,kind='manual_recording'),dict(self.event,starred=True)]:
   self.assertFalse(eligible(event,self.now,{'enabled':True}))
  self.assertFalse(eligible(self.event,self.now,{'enabled':False}))
 def test_settings_persist_and_validate(self):
  with tempfile.TemporaryDirectory() as d:
   self.assertFalse(settings(d)['daytime_auto_cleanup'])
   self.assertTrue(update(d,{'daytime_auto_cleanup':True})['daytime_auto_cleanup'])
   self.assertTrue(settings(d)['daytime_auto_cleanup'])
   with self.assertRaises(ValueError):update(d,{'daytime_auto_cleanup':'false'})
   with self.assertRaises(ValueError):update(d,{'after_seconds':0})
   self.assertFalse(update(d,{'daytime_auto_cleanup':False})['daytime_auto_cleanup'])

class AutomaticDeletionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'uap-lab';self.sessions=self.root/'sessions';self.sessions.mkdir();(self.data/'email-reviews/examples').mkdir(parents=True)
  self.key='a'*32;self.folder=self.root/'notifications/outbox'/self.key;self.folder.mkdir(parents=True)
  self.rise,_=daylight(datetime(2026,11,9).date());self.now=self.rise+5*3600
  self.event=dict(id=self.key,generation='run-abc',pts_seconds=5,created_epoch=self.now,detected_epoch=self.rise+1,classification='not_anomalous')
  save(self.folder/'event.json',self.event);self.media=self.folder/'object.png';self.media.write_bytes(b'pixels');update(self.root,{'daytime_auto_cleanup':True})
 def tearDown(self):self.tmp.cleanup()
 def run_cycle(self,apply=True):
  with patch('review_retention.time.time',return_value=self.now):return cycle(self.data,self.sessions,{},apply=apply)
 def test_deletes_media_and_hides_stale_library_rows(self):
  result=self.run_cycle();self.assertEqual(result['daytime_expired'],1);self.assertFalse(self.media.exists())
  from retired_data import ids,visible
  samples,events=ids(self.data);self.assertFalse(visible(dict(kind='detection',id=self.key),samples,events))
  self.assertEqual(self.run_cycle()['deleted_files'],0)
 def test_human_review_and_manual_original_are_protected(self):
  record=dict(event_id=self.key,sample_id=self.key,human_confirmed=True,label='anomalous',reviewed_epoch=1)
  save(self.data/'email-reviews/examples'/self.key/'review.json',record)
  self.assertEqual(self.run_cycle()['daytime_expired'],0);self.assertTrue(self.media.exists())
 def test_dry_run_and_active_event_preserve_pixels(self):
  self.assertEqual(self.run_cycle(False)['daytime_expired'],1);self.assertTrue(self.media.exists());self.assertFalse((self.data/'retired-objects.json').exists())
  save(self.folder.parent/'producer-state.json',dict(groups=[dict(id=self.key)]))
  self.assertEqual(self.run_cycle()['daytime_expired'],0);self.assertTrue(self.media.exists())
 def test_manual_session_and_shared_original_survive(self):
  evidence=self.root/'notifications/evidence/run-abc/segment-000000001.mkv';evidence.parent.mkdir(parents=True);evidence.write_bytes(b'manual original')
  save(self.folder/'review-source.json',dict(generation='run-abc',segments=[dict(file=evidence.name)]))
  folder=self.sessions/'manual-session';save(folder/'manifest.json',dict(capture_origin='manual',state='completed',spool_generation='run-abc'))
  save(folder/'buffer-state.json',dict(segments=[dict(file=evidence.name,start=0,end=10)]));video=folder/'video.mp4';video.write_bytes(b'manual video')
  self.run_cycle();self.assertTrue(evidence.exists());self.assertTrue(video.exists())
 def test_disable_while_waiting_for_deletion_lease(self):
  from contextlib import contextmanager
  @contextmanager
  def lease(*args):
   update(self.root,{'daytime_auto_cleanup':False});yield True
  with patch('review_playback.event_lease',lease):self.run_cycle()
  self.assertTrue(self.media.exists());self.assertFalse((self.data/'retired-objects.json').exists())
 def test_nighttime_and_new_daytime_remain(self):
  for stamp in (self.rise-1,self.now-100):
   save(self.folder/'event.json',dict(self.event,detected_epoch=stamp))
   self.assertEqual(self.run_cycle()['daytime_expired'],0);self.assertTrue(self.media.exists())
