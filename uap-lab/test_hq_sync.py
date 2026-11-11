import contextlib,json,tempfile,types,sys,unittest
from pathlib import Path
from unittest.mock import patch
import hq_sync
class FieldSyncTests(unittest.TestCase):
 def test_conflicting_decision_does_not_call_label(self):
  self.run_case(conflict=True)
 def test_retry_is_idempotent(self):
  self.run_case(conflict=False)
 def run_case(self,conflict):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);key='a'*32;request='b'*32;p=root/'email-reviews/examples'/key/'review.json';p.parent.mkdir(parents=True)
   record=dict(event_id=key,sample_id=key,label='anomalous',human_confirmed=True,reviewed_epoch=1);p.write_text(json.dumps(record));calls=[]
   def label(data,item):
    calls.append(item);record.update(label=item['label'],reviewed_epoch=2,message_id='quick-label:'+request);p.write_text(json.dumps(record));return dict(saved=True)
   fake=types.SimpleNamespace(_SAVE_LOCK=contextlib.nullcontext(),label=label)
   with patch.dict(sys.modules,{'detection_library':fake}),patch('email_training.review_batch',lambda *_:contextlib.nullcontext()):
    item=dict(id=key,label='not_anomalous',request_id=request,base_revision='unreviewed' if conflict else hq_sync.revision(record),reviewer='HQ')
    first=hq_sync.apply_reviews(root,dict(items=[item]))['results'][0]
    if conflict:self.assertEqual(first['state'],'conflict');self.assertEqual(calls,[])
    else:
     self.assertEqual(first['state'],'synced');second=hq_sync.apply_reviews(root,dict(items=[item]))['results'][0];self.assertEqual(first,second);self.assertEqual(len(calls),1)
 def test_snapshot_revision_matches_authoritative_record(self):
  record=dict(sample_id='a'*32,label='anomalous',human_confirmed=True,reviewed_epoch=123.5)
  equivalent=dict(sample_id='a'*32,label='anomalous',human_confirmed=True,reviewed_epoch=123.5,event_id='b'*32,message_id='irrelevant')
  self.assertEqual(hq_sync.revision(record),hq_sync.revision(equivalent))
if __name__=='__main__':unittest.main()
