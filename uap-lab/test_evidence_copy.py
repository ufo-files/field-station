import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from evidence_copy import copy_evidence

class EvidenceCopyTests(unittest.TestCase):
 def test_real_copy_has_independent_mutations(self):
  with tempfile.TemporaryDirectory() as tmp:
   src=Path(tmp)/'src';dst=Path(tmp)/'dst';src.write_bytes(b'original evidence')
   method=copy_evidence(src,dst)
   self.assertEqual(dst.read_bytes(),src.read_bytes());self.assertNotEqual(src.stat().st_ino,dst.stat().st_ino)
   dst.write_bytes(b'changed');self.assertEqual(src.read_bytes(),b'original evidence')
   self.assertIn(method,('clone','copy'))
 def test_unsupported_and_cross_device_fallback(self):
  for error in (errno.ENOTSUP,errno.EXDEV):
   with tempfile.TemporaryDirectory() as tmp,patch('evidence_copy._clone',side_effect=OSError(error,'fixture')):
    src=Path(tmp)/'src';dst=Path(tmp)/'dst';src.write_bytes(b'evidence')
    self.assertEqual(copy_evidence(src,dst),'copy');self.assertEqual(dst.read_bytes(),b'evidence')
 def test_io_errors_not_silently_retried(self):
  with patch('evidence_copy._clone',side_effect=OSError(errno.EIO,'fixture')),patch('builtins.open') as op:
   with self.assertRaises(OSError):copy_evidence('source','dest')
   op.assert_not_called()
 def test_existing_destination_is_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:
   src=Path(tmp)/'src';dst=Path(tmp)/'dst';src.write_bytes(b'source');dst.write_bytes(b'existing')
   with self.assertRaises(FileExistsError):copy_evidence(src,dst)
   self.assertEqual(dst.read_bytes(),b'existing')

if __name__=='__main__':unittest.main()
