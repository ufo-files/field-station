import hashlib,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from email_training import store_review,reviewed_examples
from email_review import detail,remove_review,finish_review

class MultipleAnnotations(unittest.TestCase):
 def test_independent_objects_corrections_and_removal(self):
  with tempfile.TemporaryDirectory() as tmp:
   data=Path(tmp)/'lab';event='a'*32;folder=Path(tmp)/'notifications/outbox'/event;folder.mkdir(parents=True)
   (folder/'event.json').write_text(json.dumps(dict(bounds=[1,2,8,8],generation='g',pts_seconds=3)))
   session=Path(tmp)/'sessions/20261031T120000Z-abcdef';session.mkdir(parents=True)
   (session/'manifest.json').write_text(json.dumps(dict(spool_generation='g')))
   (session/'buffer-state.json').write_text(json.dumps(dict(segments=[dict(start=0,end=10)])))
   (session/'archive-decision.json').write_text(json.dumps(dict(bundle_ready=True)))
   (folder/'review-clip.json').write_text(json.dumps(dict(state='ready',event_time=1,timeline=[dict(time=1),dict(time=2)])))
   out=io.BytesIO();Image.new('RGB',(8,8)).save(out,format='PNG');crop=out.getvalue()
   records=[]
   for i,(label,frame) in enumerate([('bird',1),('insect',1),('airplane',2)],1):
    r=dict(event_id=event,sample_id=str(i)*32,label=label,review_clip_time=frame,reviewed_epoch=i,source='station_web_review',message_id=str(i),human_confirmed=True,multiclass_ready=True,generation='g',native_crop_sha256=hashlib.sha256(crop).hexdigest(),bounds=[1,2,8,8]);records.append(r);store_review(data,r,crop)
   self.assertEqual(len(detail(data,event)['annotations']),3)
   self.assertEqual(len({r['id'] for r in reviewed_examples(data)}),3)
   finish_review(data,dict(id=event,completed=True))
   self.assertTrue(detail(data,event)['completed'])
   self.assertFalse(json.loads((session/'archive-decision.json').read_text())['bundle_ready'])
   corrected=dict(records[0],label='drone',message_id='correction',reviewed_epoch=4);store_review(data,corrected,crop)
   self.assertEqual({r['label'] for r in reviewed_examples(data)},{'drone','insect','airplane'})
   self.assertFalse(detail(data,event)['completed'])
   finish_review(data,dict(id=event,completed=True))
   finish_review(data,dict(id=event,completed=False))
   self.assertFalse(detail(data,event)['completed'])
   remove_review(data,dict(id=event,sample_id=records[1]['sample_id']))
   self.assertEqual(len(detail(data,event)['annotations']),2)
   self.assertEqual({r['label'] for r in reviewed_examples(data)},{'drone','airplane'})
   self.assertEqual(len(list((data/'email-reviews/history').glob('*.json'))),5)
 def test_index_reads_current_records_and_recovers_new_unindexed_samples(self):
  import os
  from unittest.mock import patch
  from email_review import event_reviews
  with tempfile.TemporaryDirectory() as tmp:
   data=Path(tmp);root=data/'email-reviews';examples=root/'examples';sample=examples/('b'*32);sample.mkdir(parents=True);key='a'*32
   row=dict(event_id=key,sample_id='b'*32,label='tree',reviewed_epoch=1)
   (sample/'review.json').write_text(json.dumps(row));manifest=root/'training-manifest.json';manifest.write_text(json.dumps({'examples':[row]}))
   (sample/'review.json').write_text(json.dumps(dict(row,label='bird',deleted=True)))
   with patch.object(Path,'glob',side_effect=AssertionError('Full scan should not run')):
    self.assertEqual(event_reviews(data,key)[0]['label'],'bird');self.assertTrue(event_reviews(data,key)[0]['deleted'])
   extra=examples/('c'*32);extra.mkdir();(extra/'review.json').write_text(json.dumps(dict(row,sample_id='c'*32)))
   os.utime(manifest,(1,1))
   self.assertEqual(len(event_reviews(data,key)),2)

if __name__=='__main__':unittest.main()
