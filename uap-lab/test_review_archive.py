import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import lab
from review_archive import record_decision,sync_decisions
class ReviewArchiveTests(unittest.TestCase):
 def test_unconfirmed_suggestions_never_authorize_archive(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   self.assertIsNone(record_decision(root,{'provenance':{'session_id':'20261029T230000Z-abcdef'}},dict(completed=False)))
 def test_reviewed_objects_and_no_target_produce_distinct_decisions(self):
  for label,expected in [('anomalous',True),('bird',False),(None,False)]:
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);data=root/'lab';data.mkdir();folder=data/'video';folder.mkdir();station=root/'station';sid='20261029T230000Z-abcdef';session=station/'sessions'/sid;session.mkdir(parents=True);lab.save(session/'manifest.json',{'id':sid})
    lab.save(folder/'annotations.json',[{'label':label}] if label else [])
    meta={'id':'a'*32,'sha256':'b'*64,'provenance':{'session_id':sid}}
    with patch.object(lab,'DATA',data),patch.object(lab,'STATION',station):
     d=record_decision(folder,meta,{'completed':True,'reviewed_at':100,'no_target':label is None});self.assertEqual(d['confirmed_anomalous'],expected);sync_decisions();self.assertEqual(lab.read(session/'archive-decision.json'),d)
