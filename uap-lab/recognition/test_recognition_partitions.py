import sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from recognition_store import RecognitionStore
from recognition_history import History

class PartitionTests(unittest.TestCase):
    def test_rollover_keeps_checkpoint_history_and_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'results.sqlite';store=RecognitionStore(path);store.partition_bytes=1
            for n in range(3):
                store.add('run',dict(sequence=n,pts_seconds=n,received_epoch=n,observations=[]),'model')
                store.commit(dict(last_sequence=n),None)
            self.assertEqual(store.db.execute('SELECT count(*) FROM frames').fetchone()[0],0)
            store.close();store=RecognitionStore(path)
            self.assertEqual(store.load()[0]['last_sequence'],2)
            with closing(History(path)) as history:
                rows=list(history.execute('SELECT sequence,model,observations FROM frames WHERE generation=? AND sequence BETWEEN ? AND ? ORDER BY sequence',('run',0,2)))
                self.assertEqual([r[0] for r in rows],[0,1,2])
                self.assertEqual(history.execute('SELECT pts FROM frames WHERE generation=? ORDER BY pts DESC LIMIT 1',('run',)).fetchone(),(2.0,))
            with self.assertRaises(sqlite3.IntegrityError):store.add('run',dict(sequence=1,pts_seconds=1,received_epoch=1,observations=[]),'model')
            store.close()
    def test_published_snapshot_before_prune_recovers_without_duplicate_results(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'results.sqlite';store=RecognitionStore(path)
            store.add('run',dict(sequence=0,pts_seconds=0,received_epoch=0,observations=[]),'model');store.commit(dict(last_sequence=0),None)
            folder=path.parent/'partitions';folder.mkdir();db=sqlite3.connect(folder/'1.sqlite');store.db.backup(db);db.close()
            with closing(History(path)) as history:self.assertEqual(len(list(history.execute('SELECT sequence,model,observations FROM frames WHERE generation=? ORDER BY sequence',('run',)))),1)
            store.close();store=RecognitionStore(path)
            self.assertEqual(store.db.execute('SELECT count(*) FROM frames').fetchone()[0],0);self.assertEqual(store.load()[0]['last_sequence'],0);store.close()
if __name__=='__main__':unittest.main()
