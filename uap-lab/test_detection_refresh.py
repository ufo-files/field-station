import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import detection_library as library
class RefreshTests(unittest.TestCase):
 def test_rebuild_keeps_complete_cache_until_atomic_replacement(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);old=[{'id':'old'}];new=[{'id':'new'}];entered=threading.Event();release=threading.Event()
   library._CACHE[str(root)]=(0,old)
   def build(data,publish):
    publish([]);entered.set();release.wait(5);return new
   try:
    with patch.object(library,'collect',side_effect=build):
     cached,busy,error=library.refresh(root)
     self.assertTrue(busy);self.assertTrue(entered.wait(2))
     self.assertEqual(library._CACHE[str(root)][1],old)
     done=library._BUILDING[str(root)];release.set();self.assertTrue(done.wait(2))
     self.assertEqual(library.refresh(root)[0][1],new)
   finally:release.set();library.invalidate()
