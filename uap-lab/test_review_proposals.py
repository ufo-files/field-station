import json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import recognition_review
class Suggestions(unittest.TestCase):
 def test_pagination_and_sha_review_protection(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'video';folder.mkdir();(root/'recognition').mkdir();meta=dict(sha256='a'*64,width=1920,height=1080);records={str(folder/'video.json'):meta};fake=SimpleNamespace(DATA=root,video_path=lambda _:folder,read=lambda path,default=None: records.get(str(path),default))
   c=sqlite3.connect(root/'recognition/results.sqlite');c.execute('CREATE TABLE frames(generation TEXT,sequence INTEGER,observations TEXT)');objects=[dict(box=[1,2,3,4],proposed_track_id=str(i),suggested_label='bird',scores={'bird':.9},ambiguous_link=False,direction_change_degrees=None) for i in range(105)];c.execute('INSERT INTO frames VALUES(?,?,?)',('run',1,json.dumps(objects)));c.commit();c.close()
   with patch.dict(sys.modules,lab=fake),patch.object(recognition_review,'mapping',return_value=dict(generation='run',frames=[dict(sequence=1,time=.1)])):
    first=recognition_review.proposals('video');second=recognition_review.proposals('video',after=first['next_after']);self.assertEqual(len(first['items']),100);self.assertEqual(len(second['items']),5);self.assertEqual(first['total_suggestions'],105);self.assertFalse(first['items'][0]['human_confirmed']);self.assertIsNone(second['next_after'])
    records[str(root/'reviewed-videos.json')]={'a'*64:{'completed':True}};self.assertEqual(recognition_review.proposals('video')['items'],[])
    records[str(root/'reviewed-videos.json')]={};records[str(root/'omitted-videos.json')]={'a'*64:{'excluded':True}};self.assertEqual(recognition_review.proposals('video')['items'],[])
