import json,tempfile,unittest
from pathlib import Path
from PIL import Image
from snapshot import collect
class SnapshotTests(unittest.TestCase):
 def test_multiple_objects_in_one_frame_are_separate_training_samples(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'videos'/'video';folder.mkdir(parents=True)
   (folder/'video.json').write_text(json.dumps({'sha256':'recording'}))
   annotations=[]
   for i,label in enumerate(['tree','house','tree','antenna','vehicle']):
    name=f'{i}.png';Image.new('RGB',(8,8),(i,20,30)).save(folder/name)
    annotations.append(dict(id=str(i),image=name,label=label,frame_index=42,time=1.4))
   (folder/'annotations.json').write_text(json.dumps(annotations))
   manifest,images=collect(root)
   self.assertEqual(len(manifest['samples']),5);self.assertEqual(len(images),5)
   self.assertEqual(len({r['origin'] for r in manifest['samples']}),5)
   self.assertEqual({r['group'] for r in manifest['samples']},{'sha:recording'})
