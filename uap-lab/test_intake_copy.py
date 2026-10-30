import unittest
from unittest.mock import patch
import lab
from test_lab import GenericIntakeTests

class IntakeCopyTests(unittest.TestCase):
 setUp=GenericIntakeTests.setUp
 tearDown=GenericIntakeTests.tearDown
 def test_changing_source_never_enters_library(self):
  original=lab.copy_evidence
  def changed(source,destination):
   result=original(source,destination);source.write_bytes(b'changed input during copy');return result
  with patch.object(lab,'copy_evidence',side_effect=changed):
   with self.assertRaisesRegex(ValueError,'changed during import'):lab.import_training_file(self.input)
  self.assertEqual(list((lab.DATA/'videos').glob('*/source')),[])
  self.assertEqual(list((lab.DATA/'videos').glob('*/source.part-*')),[])
  self.assertEqual(list((lab.DATA/'videos').glob('*/video.json')),[])
 def test_partial_copy_failure_keeps_source_and_cleans_temporary(self):
  def failed(source,destination):
   destination.write_bytes(b'partial');raise OSError('fixture disk failure')
  with patch.object(lab,'copy_evidence',side_effect=failed):
   with self.assertRaisesRegex(OSError,'fixture disk failure'):lab.import_training_file(self.input)
  self.assertEqual(self.input.read_bytes(),b'video content A')
  self.assertEqual(list((lab.DATA/'videos').glob('*/source*')),[])
