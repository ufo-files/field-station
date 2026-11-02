import contextlib,json,sys,types,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import label_queue
class DirectSave(unittest.TestCase):
 def test_save_retry_and_undo_visibility_preserve_previous_labels(self):
  with tempfile.TemporaryDirectory() as tmp:
   data=Path(tmp);vid='a'*32;p=data/'videos'/vid;p.mkdir(parents=True)
   (p/'video.json').write_text(json.dumps(dict(id=vid,duration=1,sha256='source')));(p/'source').write_bytes(b'original')
   old=dict(id='b'*32,label='bird');(p/'annotations.json').write_text(json.dumps([old]));calls=[]
   def save(path,value):path.write_text(json.dumps(value))
   def annotate(key,seconds,bounds,label,annotation_id):
    calls.append((key,seconds,bounds,label));rows=label_queue.read(p/'annotations.json',[]);rows.append(dict(id=annotation_id,label=label));save(p/'annotations.json',rows)
   lab=types.SimpleNamespace(DATA=data,checked_id=lambda x:x,video_path=lambda x:data/'videos'/x,_per_video_lock=lambda *_:contextlib.nullcontext(),_REVIEW_LOCKS={},annotate=annotate,save=save)
   with patch.dict(sys.modules,lab=lab):
    body=dict(id=vid,kind='video',label='cloud',request_id='c'*32)
    result=label_queue.label(data,body);again=label_queue.label(data,body)
    self.assertEqual(result,again);self.assertEqual(len(calls),1)
    self.assertEqual(calls[0],(vid,0,dict(x=0,y=0,w=1,h=1),'cloud'))
    self.assertEqual(label_queue.videos(data)['items'],[])
    self.assertEqual(label_queue.read(p/'annotations.json',[])[0],old)
    self.assertFalse((p/'review.json').exists(),'Do not claim the whole video was reviewed')
    save(p/'annotations.json',[old])
    self.assertEqual(label_queue.videos(data)['items'][0]['id'],vid)
    save(p/'training-excluded.json',dict(excluded=True))
    with self.assertRaises(ValueError):label_queue.label(data,dict(body,request_id='d'*32))
if __name__ == '__main__':unittest.main()
