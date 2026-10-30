import json,tempfile,threading,time,os,unittest
from pathlib import Path
from unittest.mock import patch
from spool_events import SpoolEvents,atomic
from spool_gc import cleanup
class SpoolTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.run=self.root/'run-abcdef';self.run.mkdir()
 def tearDown(self):self.temp.cleanup()
 def event(self,pts,seq):return dict(pts_seconds=pts,sequence=seq,received_epoch=1000+pts)
 def test_late_analysis_preserves_ten_seconds_before_and_after(self):
  events=SpoolEvents(self.root);events.update(self.event(20,1200),[[2,2,5,5]],{},self.run.name,'a'*32)
  events.update(self.event(30.1,1806),[],{},self.run.name,'a'*32)
  records=list((self.run/'events').glob('*.json'));self.assertEqual(len(records),1);event=json.loads(records[0].read_text());self.assertEqual(event['start_pts'],10);self.assertEqual(event['end_pts'],30)
 def test_restart_continues_same_open_event_without_duplicate_candidates(self):
  events=SpoolEvents(self.root);events.update(self.event(20,1200),[[2,2,5,5]],{},self.run.name,None);sid=events.event['session_id'];events.acknowledge(self.run.name,dict(last_sequence=1200,last_pts_seconds=20))
  recovered=SpoolEvents(self.root);recovered.update(self.event(20,1200),[[2,2,5,5]],{},self.run.name,None);self.assertEqual(recovered.event['session_id'],sid);self.assertEqual(len((self.run/'candidates'/(sid+'.jsonl')).read_text().splitlines()),1)
 def test_cleanup_requires_age_acknowledgment_and_no_pending_event(self):
  meta=dict(file='segment-000000000.mkv',start=0,end=1,start_epoch=1000,end_epoch=1001,bytes=5);source=self.run/meta['file'];source.write_bytes(b'video');atomic(self.run/(meta['file']+'.json'),meta)
  self.assertEqual(cleanup(self.root,now=100000),0)
  atomic(self.run/'analysis-ack.json',dict(generation=self.run.name,last_pts_seconds=100,integrity_ok=True))
  self.assertEqual(cleanup(self.root,now=1002),0)
  atomic(self.run/'open-event.json',dict(start_pts=0,end_pts=10,state='open'))
  self.assertEqual(cleanup(self.root,now=100000),0)
  (self.run/'open-event.json').unlink();self.assertEqual(cleanup(self.root,now=100000),1)
 def test_hardlinked_event_survives_spool_retention(self):
  source=self.run/'segment-000000000.mkv';source.write_bytes(b'original');evidence=self.root/'event.mkv';os.link(source,evidence)
  atomic(self.run/(source.name+'.json'),dict(file=source.name,start=0,end=1,end_epoch=1000));atomic(self.run/'analysis-ack.json',dict(generation=self.run.name,last_pts_seconds=100,integrity_ok=True));cleanup(self.root,now=100000);self.assertEqual(evidence.read_bytes(),b'original')
 def test_index_cursor_retains_pending_window_and_timestamp_neighbors(self):
  entries=[]
  for i in range(8):
   name=f'segment-{i:09d}.mkv';(self.run/name).write_bytes(b'evidence');entries.append(dict(file=name,start=i,end=i+1,end_epoch=1000+i))
   (self.run/f'frame-times-{i:09d}.jsonl').write_text('timestamp')
  (self.run/'segments-index.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in entries))
  atomic(self.run/'analysis-ack.json',dict(generation=self.run.name,last_pts_seconds=100,integrity_ok=True));atomic(self.run/'open-event.json',dict(start_pts=5,end_pts=20,state='open'))
  self.assertEqual(cleanup(self.root,now=100000),5);self.assertTrue((self.run/'frame-times-000000002.jsonl').exists());self.assertTrue((self.run/'frame-times-000000003.jsonl').exists());self.assertTrue((self.run/'segment-000000005.mkv').exists());self.assertEqual(cleanup(self.root,now=100000),0)

 def test_continuous_motion_window_keeps_full_post_roll(self):
  events=SpoolEvents(self.root)
  for i in range(401):events.update(self.event(20+i/10,1200+i),[[2,2,5,5]],{},self.run.name,None)
  records=list((self.run/'events').glob('*.json'));self.assertEqual(len(records),1);event=json.loads(records[0].read_text());self.assertEqual(event['finish_reason'],'window_limit');self.assertAlmostEqual(event['end_pts']-event['last_seen_pts'],10);self.assertLessEqual(event['end_pts']-event['start_pts'],60);self.assertAlmostEqual(events.event['onset_pts']-events.event['start_pts'],10)

class AlertRetentionTests(unittest.TestCase):
 def test_alert_pin_moves_to_verified_native_copy(self):
  import hashlib
  from alert_evidence import preserve,backed_up
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);spool=root/'capture-spool';run=spool/'run-abc';run.mkdir(parents=True)
   entry=dict(file='segment-000000000.mkv',start=0,end=12,start_epoch=1,end_epoch=13,bytes=5,sha256=hashlib.sha256(b'video').hexdigest())
   (run/entry['file']).write_bytes(b'video');(run/'segments-index.jsonl').write_text(json.dumps(entry)+'\n');atomic(run/'analysis-ack.json',dict(generation=run.name,last_pts_seconds=100,integrity_ok=True))
   folder=root/'notifications/outbox'/('a'*32);folder.mkdir(parents=True);event=dict(generation=run.name,pts_seconds=6);atomic(folder/'event.json',event);atomic(folder/'delivery.json',dict(state='accepted_by_mail'))
   self.assertEqual(cleanup(spool,now=100000),0)
   self.assertEqual(preserve(root)['errors'],[]);self.assertTrue(backed_up(root,event,folder));self.assertEqual(cleanup(spool,now=100000),1)
   self.assertEqual((root/'notifications/evidence'/run.name/entry['file']).read_bytes(),b'video')
 def test_bad_checksum_keeps_raw_alert_context(self):
  from alert_evidence import preserve
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);run=root/'capture-spool/run-abc';run.mkdir(parents=True);entry=dict(file='segment-000000000.mkv',start=0,end=12,bytes=5,sha256='wrong')
   (run/entry['file']).write_bytes(b'video');(run/'segments-index.jsonl').write_text(json.dumps(entry)+'\n');folder=root/'notifications/outbox'/('a'*32);atomic(folder/'event.json',dict(generation=run.name,pts_seconds=6));self.assertTrue(preserve(root)['errors']);self.assertFalse((folder/'review-source.json').exists())
