import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import video_tags,lab
from archive_tags import normalize,subjects

class TagsTests(unittest.TestCase):
 def test_normalization_and_reserved_tags(self):
  self.assertEqual(normalize([' meteor ','Meteor','red light']),['meteor','red light'])
  for tags in [['ce5-tones'],['CE5-TONES'],['bad;tag'],['a'*65],'meteor']:
   with self.assertRaises(ValueError):normalize(tags)
  self.assertNotIn('ce5-tones',subjects(dict(custom_tags=['meteor'])))
 def test_save_reload_remove_and_conflict(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);data=root/'uap-lab';folder=root/'sessions/20261107T100000Z-abcdef';folder.mkdir(parents=True)
   with patch('video_tags.session_for',return_value=folder):
    state=video_tags.save(data,dict(id='event',tags=['meteor'],revision=None))
    self.assertEqual(video_tags.status(data,'event')['custom'],['meteor'])
    with self.assertRaises(ValueError):video_tags.save(data,dict(id='event',tags=['wrong'],revision=None))
    state=video_tags.save(data,dict(id='event',tags=[],revision=state['revision']))
    self.assertEqual(state['custom'],[])
