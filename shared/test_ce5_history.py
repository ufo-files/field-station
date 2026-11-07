import tempfile,unittest
from ce5_history import begin,observed,overlap

class HistoryTests(unittest.TestCase):
 def test_interval_boundaries_and_restart(self):
  with tempfile.TemporaryDirectory() as root:
   self.assertEqual(overlap(root,dict(started_epoch=100,stopped_epoch=200)),[])
   identity=begin(root,'/private/ce5.mp3',110)
   self.assertEqual(overlap(root,dict(started_epoch=100,stopped_epoch=200)),[])
   observed(root,identity,130)
   for start,end,expected in [(100,120,True),(120,140,True),(110,130,True),(100,110,False),(130,140,False),(200,300,False)]:
    self.assertEqual(bool(overlap(root,dict(started_epoch=start,stopped_epoch=end))),expected)
   self.assertEqual(overlap(root,dict(started_epoch=100,stopped_epoch=200,clip_end_epoch=105)),[])
   self.assertEqual(overlap(root,dict(started_epoch=100)),[])
   self.assertEqual(overlap(root,dict(started_epoch=100,stopped_epoch=200))[0]['track'],'ce5.mp3')
