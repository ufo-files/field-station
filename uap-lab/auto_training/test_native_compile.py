import sys,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_compile import compile_model
class CompilationRetry(unittest.TestCase):
 def test_retry_replaces_previous_artifact(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'model.mlmodelc';p.mkdir();(p/'old').touch()
   def compiler(args,**kwargs):
    target=Path(args[2]);target.mkdir();(target/'new').touch()
   with patch('native_compile.subprocess.run',side_effect=compiler):compile_model('compiler','source',p)
   self.assertEqual([x.name for x in p.iterdir()],['new'])
 def test_failed_compile_preserves_previous_artifact(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'model.mlmodelc';p.mkdir();(p/'old').touch()
   with patch('native_compile.subprocess.run',side_effect=subprocess.CalledProcessError(1,['compiler'],stderr=b'actual cause')):
    with self.assertRaisesRegex(RuntimeError,'actual cause'):compile_model('compiler','source',p)
   self.assertTrue((p/'old').exists())
if __name__=='__main__':unittest.main()
