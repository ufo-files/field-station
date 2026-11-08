import json
from pathlib import Path
import tempfile
import unittest
from recognition_alerts import AlertOutbox

class RecoveryTests(unittest.TestCase):
 def test_recover_only_active_unpublished_groups(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);key='a'*32;missing='b'*32
   (root/'producer-state.json').write_text(json.dumps({'groups':[{'id':key},{'id':missing}]}))
   (root/key).mkdir();(root/key/'event.json').write_text(json.dumps({'group_id':key,'group_first_pts':1}))
   # Historical records are unrelated to active recovery and must not be opened.
   (root/'old').mkdir();(root/'old/event.json').write_text('unreadable historical record')
   result=AlertOutbox(root)
   self.assertTrue(result.groups[0]['notified'])
   self.assertNotIn('notified',result.groups[1])
