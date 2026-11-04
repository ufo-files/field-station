import hashlib,json
from test_label_queue import QueueTests
import retired_data
from email_training import store_review

class RetirementTests(QueueTests):
 def retired(self,key='00000000000000000000000000000001',sample=None,label='landscape'):
  record=dict(event_id=key,sample_id=sample or key,label=label,human_confirmed=True,source='station_web_review',message_id=sample or key,reviewed_epoch=1,native_crop_sha256=hashlib.sha256(self.crop).hexdigest())
  store_review(self.data,record,self.crop);return key,sample or key
 def test_retirement_deletes_media_and_keeps_tombstones(self):
  key,sample=self.retired();before=retired_data.retire(self.data)
  self.assertFalse(before['applied']);self.assertGreater(before['bytes'],0)
  retired_data.retire(self.data,True)
  self.assertFalse((self.root/'notifications/outbox'/key).exists())
  folder=self.data/'email-reviews/examples'/sample
  self.assertFalse((folder/'native-object.png').exists());self.assertTrue(json.loads((folder/'review.json').read_text())['retired'])
  samples,events=retired_data.ids(self.data);self.assertIn(key,events);self.assertIn(sample,samples)
  self.assertFalse(retired_data.visible(dict(id=key,kind='detection'),samples,events))
  self.assertEqual(retired_data.retire(self.data,True)['bytes'],0)
 def test_shared_valid_review_preserves_event_media(self):
  key,sample=self.retired();_,valid=self.retired(key,'a'*32,'anomalous')
  result=retired_data.retire(self.data,True)
  self.assertEqual(result['protected_shared_events'],1)
  self.assertTrue((self.root/'notifications/outbox'/key/'object.png').exists())
  self.assertTrue((self.data/'email-reviews/examples'/valid/'native-object.png').exists())
  self.assertFalse((self.data/'email-reviews/examples'/sample/'native-object.png').exists())
