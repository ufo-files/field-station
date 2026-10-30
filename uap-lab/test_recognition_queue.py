import json,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import lab
from recognition_queue import local_summary
class LocalQueueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data=self.root/'lab';self.station=self.root/'station';self.sid='20261029T230000Z-abcdef';self.vid='a'*32
  (self.data/'recognition').mkdir(parents=True);(self.station/'sessions'/self.sid).mkdir(parents=True)
  self.patches=[patch.object(lab,'DATA',self.data),patch.object(lab,'STATION',self.station)];[p.start() for p in self.patches]
  self.meta={'id':self.vid,'provenance':{'session_id':self.sid}}
  lab.save(self.station/'sessions'/self.sid/'manifest.json',{'spool_generation':'run-a'})
  lab.save(self.station/'sessions'/self.sid/'buffer-state.json',{'segments':[{'start':1,'end':2}]})
  lab.save(self.data/'recognition/status.json',{'generation':'run-a','coverage_start_pts':1})
  with closing(sqlite3.connect(self.data/'recognition/results.sqlite')) as db, db:
   db.execute('CREATE TABLE frames(generation TEXT, sequence INTEGER, pts REAL, model TEXT, observations TEXT)')
   db.executemany('INSERT INTO frames VALUES(?,?,?,?,?)',[('run-a',i,1+i/60,'model-a',json.dumps([{'suggested_label':'unknown'}] if i==5 else [])) for i in range(61)])
  self.origin={'generation':'run-a','frames':[{'sequence':i} for i in range(60)]}
 def tearDown(self):
  [p.stop() for p in reversed(self.patches)];self.tmp.cleanup()
 def test_all_native_frames_reused_without_confirming_unknown(self):
  with patch('recognition_review.mapping',return_value=self.origin):r=local_summary(self.meta)
  self.assertEqual(r['state'],'review_required');self.assertEqual(r['processed_frames'],60);self.assertEqual(r['suggested_label_counts'],{'unknown':1});self.assertFalse(r['automatic_deletion']);self.assertFalse(r['human_confirmed'])
 def test_missing_frame_is_never_complete_or_negative(self):
  with closing(sqlite3.connect(self.data/'recognition/results.sqlite')) as db, db:db.execute('DELETE FROM frames WHERE sequence=30')
  with patch('recognition_review.mapping',return_value=self.origin):r=local_summary(self.meta)
  self.assertEqual(r['state'],'waiting_local_analysis');self.assertEqual(r['processed_frames'],59)
 def test_pending_checkpoint_does_not_run_mapping(self):
  with closing(sqlite3.connect(self.data/'recognition/results.sqlite')) as db, db:db.execute('DELETE FROM frames WHERE sequence>20')
  with patch('recognition_review.mapping') as mapping:r=local_summary(self.meta);mapping.assert_not_called()
  self.assertEqual(r['state'],'waiting_local_analysis')
 def test_precoverage_retains_reference_path(self):
  lab.save(self.data/'recognition/status.json',{'generation':'run-a','coverage_start_pts':3})
  with patch('recognition_review.mapping') as mapping:self.assertIsNone(local_summary(self.meta));mapping.assert_not_called()
 def test_ambiguous_mapping_is_not_accepted(self):
  with patch('recognition_review.mapping',side_effect=ValueError('ambiguous')):
   with self.assertRaisesRegex(ValueError,'ambiguous'):local_summary(self.meta)
