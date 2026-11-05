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

class CatalogTests(unittest.TestCase):
 def test_index_avoids_unrelated_recording_reads_and_tracks_new_sessions(self):
  import os
  from session_catalog import rebuild,register_manifest,lookup
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'CAPTURE_SESSION_INDEX':str(Path(tmp)/'fast/catalog.sqlite')}):
   root=Path(tmp)/'station';data=root/'uap-lab';data.mkdir(parents=True);out=root/'notifications/outbox'/('a'*32);out.mkdir(parents=True);(out/'event.json').write_text(json.dumps(dict(generation='wanted',pts_seconds=12)))
   def recording(i,gen):
    folder=root/'sessions'/('20261104T120000Z-'+f'{i:06x}');folder.mkdir(parents=True);value=dict(spool_generation=gen,state='completed');register_manifest(folder/'manifest.json',value);(folder/'manifest.json').write_text(json.dumps(value));(folder/'buffer-state.json').write_text(json.dumps(dict(segments=[dict(start=10,end=20)])));(folder/'archive-decision.json').write_text('{"bundle_ready":true}');return folder
   wanted=recording(1,'wanted');other=recording(2,'other');self.assertIsNone(lookup(root,'wanted'));rebuild(root);later=recording(3,'wanted')
   original=Path.read_text
   def read(path,*args,**kwargs):
    if path==other/'manifest.json':raise AssertionError('Unrelated recording read on label-save path')
    return original(path,*args,**kwargs)
   with patch.object(Path,'iterdir',side_effect=AssertionError('Directory scan on indexed label-save path')),patch.object(Path,'read_text',read):invalidate_event(data,'a'*32)
   for folder in (wanted,later):self.assertFalse(json.loads((folder/'archive-decision.json').read_text())['bundle_ready'])
   self.assertTrue(json.loads((other/'archive-decision.json').read_text())['bundle_ready'])
 def test_invalid_index_requires_authoritative_fallback(self):
  import os
  from session_catalog import rebuild,lookup
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'CAPTURE_SESSION_INDEX':str(Path(tmp)/'catalog.sqlite')}):
   root=Path(tmp)/'station';(root/'sessions').mkdir(parents=True);rebuild(root);self.assertEqual(lookup(root,'missing'),[])
   (root/'session-catalog-invalid').write_text('update failed');self.assertIsNone(lookup(root,'missing'))

class WindowCatalogTests(unittest.TestCase):
 def test_closed_windows_exclude_other_times_but_active_recordings_remain(self):
  import os
  from session_catalog import rebuild,lookup,invalidate_window
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'CAPTURE_SESSION_INDEX':str(Path(tmp)/'index.sqlite')}):
   root=Path(tmp)/'station';folders=[]
   for i,(start,end,state) in enumerate([(10,20,'completed'),(30,40,'completed'),(30,40,'recording')]):
    f=root/'sessions'/('20261104T120000Z-'+f'{i:06x}');f.mkdir(parents=True);folders.append(f)
    (f/'manifest.json').write_text(json.dumps(dict(spool_generation='g',state=state)))
    (f/'buffer-state.json').write_text(json.dumps(dict(segments=[dict(start=start,end=end)])))
   rebuild(root);self.assertEqual(set(lookup(root,'g',12)),{folders[0],folders[2]})
   read=Path.read_text
   def guarded(path,*a,**kw):
    if path.parent in folders[:2]:raise AssertionError('Repeated closed recording metadata read')
    return read(path,*a,**kw)
   with patch.object(Path,'read_text',guarded):self.assertEqual(set(lookup(root,'g',20)),{folders[2]})
   invalidate_window(folders[1]/'buffer-state.json')
   (folders[1]/'buffer-state.json').write_text(json.dumps(dict(segments=[dict(start=10,end=20)])))
   self.assertEqual(set(lookup(root,'g',12)),set(folders))
