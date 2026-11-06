import hashlib,json,tempfile,unittest
from pathlib import Path
from archive_links import attach
class LinkTests(unittest.TestCase):
 def test_link_requires_current_verified_human_anomalous_annotation(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);data=root/'uap-lab';data.mkdir();sid='20261104T061554Z-f69d48';folder=root/'sessions'/sid;folder.mkdir(parents=True)
   event='a'*32;sample='b'*32;reviews=[dict(kind='alert_web',id=event,annotations=[dict(sample_id=sample,label='anomalous')])]
   def save(p,d):p.write_text(json.dumps(d))
   save(data/'archive-review-groups.json',dict(groups={sid:reviews}));revision=hashlib.sha256(json.dumps(reviews,sort_keys=True).encode()).hexdigest();save(folder/'archive-decision.json',dict(bundle_ready=True,review_revision=revision))
   row=dict(id='review:'+event+':'+sample,kind='review',video_id=event,sample_id=sample,human_reviewed=True,label='anomalous');url='https://archive.org/details/test-item'
   receipt=dict(state='verifying',url=url,verified_at=1);save(folder/'manifest.json',dict(internet_archive=receipt));self.assertNotIn('archive_url',attach(data,[dict(row)])[0])
   receipt['state']='retaining';save(folder/'manifest.json',dict(internet_archive=receipt));self.assertEqual(attach(data,[dict(row)])[0]['archive_url'],url)
   for change in [dict(label='not_anomalous'),dict(human_reviewed=False),dict(sample_id='c'*32)]:self.assertNotIn('archive_url',attach(data,[dict(row,**change)])[0])
   save(folder/'archive-decision.json',dict(bundle_ready=True,review_revision='stale'));self.assertNotIn('archive_url',attach(data,[dict(row)])[0])

 def test_bundle_requires_matching_current_uploaded_annotations(self):
  from archive_links import bundle_url
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)
   def save(name,value):(folder/name).write_text(json.dumps(value))
   save('archive-decision.json',dict(bundle_ready=True,review_revision='new'))
   save('review-annotations.json',dict(review_revision='new',annotations=[]))
   receipt=dict(state='retaining',identifier='test-item',verified_at=1,files=[dict(name='review-annotations.json',sha256=hashlib.sha256((folder/'review-annotations.json').read_bytes()).hexdigest())])
   save('manifest.json',dict(internet_archive=receipt));self.assertEqual(bundle_url(folder),'https://archive.org/compress/test-item')
   receipt['state']='uploading';save('manifest.json',dict(internet_archive=receipt));self.assertIsNone(bundle_url(folder))
   receipt['state']='retaining';receipt['files'][0]['sha256']='old';save('manifest.json',dict(internet_archive=receipt));self.assertIsNone(bundle_url(folder))
