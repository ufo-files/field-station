import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from review_archive import invalidate_event

class InvalidationTests(unittest.TestCase):
 def test_only_matching_generation_and_time_are_invalidated_without_glob(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);data=root/'uap-lab';data.mkdir();key='a'*32
   def save(p,value):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
   save(root/'notifications/outbox'/key/'event.json',dict(generation='current',pts_seconds=12))
   folders=[]
   for i,(gen,start,end,decision) in enumerate([('current',10,20,True),('other',10,20,True),('current',20,30,True),('current',10,20,False)]):
    folder=root/'sessions'/('20261104T120000Z-'+f'{i:06x}');folders.append(folder)
    save(folder/'manifest.json',dict(spool_generation=gen))
    save(folder/'buffer-state.json',dict(segments=[dict(start=start,end=end)]))
    if decision:save(folder/'archive-decision.json',dict(bundle_ready=True))
   with patch.object(Path,'glob',side_effect=AssertionError('Save must not glob across recording directories')):
    invalidate_event(data,key)
   self.assertEqual(json.loads((folders[0]/'archive-decision.json').read_text()),dict(bundle_ready=False,review_required=True))
   for folder in folders[1:3]:self.assertEqual(json.loads((folder/'archive-decision.json').read_text()),dict(bundle_ready=True))
   self.assertFalse((folders[3]/'archive-decision.json').exists())
 def test_missing_sessions(self):
  with tempfile.TemporaryDirectory() as tmp:invalidate_event(Path(tmp)/'uap-lab','a'*32)
