import json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from journal_recovery import recover_event_journal

class RecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.folder=self.root/'old';self.folder.mkdir();(self.folder/'closed.json').write_text('{}')
  (self.folder/'recognition-ack.json').write_text(json.dumps(dict(generation='old',integrity_ok=True,last_sequence=3,last_pts_seconds=.05)))
  self.dbpath=self.root/'results.sqlite';db=sqlite3.connect(self.dbpath)
  db.execute('CREATE TABLE frames(generation,sequence,pts,epoch,model,observations)')
  for n in (1,2,3):db.execute('INSERT INTO frames VALUES(?,?,?,?,?,?)',('old',n,n/60,100+n/60,'model',json.dumps([dict(box=[1,2,3,4])])))
  db.commit();db.close();self.records=[];self.saved=[]
  self.journal=SimpleNamespace(root=self.root,previous=dict(generation='old',last_sequence=0,last_pts_seconds=0,analyzed_frames=10,generation_analyzed_frames=1))
  def process(record):self.records.append(record);self.journal.previous=record[-1]
  self.journal.process=process;self.journal.persist=lambda:self.saved.append(dict(self.journal.previous))
 def test_replays_each_durable_record_and_records_limitations(self):
  self.assertEqual(recover_event_journal(self.journal,self.dbpath,dict(generation='new')),3)
  self.assertEqual([r[0]['sequence'] for r in self.records],[1,2,3])
  self.assertEqual(self.records[0][1],[[1,2,3,4]])
  self.assertEqual(self.saved[-1]['analyzed_frames'],13)
  audit=json.loads((self.folder/'analysis-recovery.json').read_text())
  self.assertFalse(audit['global_motion_metrics_available'])
  self.assertEqual(recover_event_journal(self.journal,self.dbpath,dict(generation='new')),0)
 def test_gap_does_not_acknowledge_missing_or_later_frames(self):
  db=sqlite3.connect(self.dbpath);db.execute('DELETE FROM frames WHERE sequence=2');db.commit();db.close()
  with self.assertRaisesRegex(ValueError,'Missing durable'):recover_event_journal(self.journal,self.dbpath,dict(generation='new'))
  self.assertEqual(self.journal.previous['last_sequence'],1)
  self.assertFalse((self.folder/'analysis-recovery.json').exists())
 def test_reads_rotated_records_without_duplicates(self):
  partitions=self.root/'partitions';partitions.mkdir();db=sqlite3.connect(self.dbpath);other=sqlite3.connect(partitions/'one.sqlite');db.backup(other);other.close();db.execute('DELETE FROM frames WHERE sequence<3');db.commit();db.close()
  self.assertEqual(recover_event_journal(self.journal,self.dbpath,dict(generation='new')),3)
  self.assertEqual(len(self.records),3)
