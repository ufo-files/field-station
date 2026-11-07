import tempfile,unittest
from pathlib import Path
import numpy as np
from recognition_store import RecognitionStore
class StoreTests(unittest.TestCase):
 def test_uncommitted_frames_replay_with_exact_state(self):
  with tempfile.TemporaryDirectory() as root:
   path=Path(root)/'results.sqlite';s=RecognitionStore(path);bg=np.arange(12,dtype=np.float32).reshape(3,4)
   row=dict(sequence=0,pts_seconds=0,received_epoch=10,observations=[{'proposed_track_id':'object-1'}]);s.add('run',row,'model');s.commit(dict(last_sequence=0,tracks={'object-1':{'vx':3}}),bg)
   s.add('run',dict(row,sequence=1),'model');s.close();r=RecognitionStore(path);state,restored=r.load();self.assertEqual(state['last_sequence'],0);self.assertEqual(state['tracks']['object-1']['vx'],3);np.testing.assert_array_equal(bg,restored);self.assertEqual(r.db.execute('SELECT count(*) FROM frames').fetchone()[0],1)
   r.add('run',dict(row,sequence=1),'model');r.commit(dict(last_sequence=1),bg);r.close()
 def test_duplicate_native_frame_is_rejected(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as root:
   s=RecognitionStore(Path(root)/'results.sqlite');row=dict(sequence=0,pts_seconds=0,received_epoch=10,observations=[]);s.add('run',row,'model')
   with self.assertRaises(sqlite3.IntegrityError):s.add('run',row,'model')
   s.close()
 def test_partition_recovery_preserves_all_generations_and_is_idempotent(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as root:
   path=Path(root)/'results.sqlite';s=RecognitionStore(path)
   for generation in ('a','z'):
    for seq in range(3):s.add(generation,dict(sequence=seq,pts_seconds=seq,received_epoch=10,observations=[]),'model')
   s.commit(dict(last_sequence=2),None)
   folder=path.parent/'partitions';folder.mkdir();archive=sqlite3.connect(folder/'one.sqlite');s.db.backup(archive);archive.close();s.close()
   for _ in range(2):
    s=RecognitionStore(path)
    self.assertEqual(s.db.execute('SELECT count(*) FROM frames').fetchone()[0],0)
    self.assertEqual(s.db.execute('SELECT * FROM archived_ranges ORDER BY generation').fetchall(),[('a',2),('z',2)])
    self.assertEqual(s.load()[0]['last_sequence'],2);s.close()
