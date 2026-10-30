import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from recognition_review import align
class Alignment(unittest.TestCase):
 def test_unique_packet_match_preserves_duplicate_frames(self):
  movie=[dict(data_hash=x,pts_time=i/60) for i,x in enumerate(['a','a','b'])];source=[dict(hash=x,sequence=i,pts_seconds=i/60) for i,x in enumerate(['z','a','a','b','c'])];matched=align(movie,source);self.assertEqual([x['sequence'] for x in matched],[1,2,3]);self.assertEqual(len(matched),3)
 def test_ambiguous_mapping_refused(self):
  with self.assertRaises(ValueError):align([dict(data_hash='a',pts_time=0)],[dict(hash='a',sequence=i,pts_seconds=i) for i in range(2)])
 def test_missing_packet_refused(self):
  with self.assertRaises(ValueError):align([dict(data_hash='x',pts_time=0)],[dict(hash='a',sequence=0,pts_seconds=0)])
