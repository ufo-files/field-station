import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab'))
from reply_reviews import parse_reply,ingest
from email_training import reviewed_examples
class ReplyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.key='a'*32;self.folder=self.root/'outbox'/self.key;self.folder.mkdir(parents=True);self.data=self.root/'lab';self.config=dict(outbox=str(self.folder.parent),lab_data=str(self.data),recipient='owner@example.org');Image.new('RGB',(21,13),'white').save(self.folder/'native-object.png');digest=hashlib.sha256((self.folder/'native-object.png').read_bytes()).hexdigest()
  (self.folder/'event.json').write_text(json.dumps(dict(schema=3,id=self.key,native_crop='native-object.png',native_crop_sha256=digest,generation='run-a',sequence=10,pts_seconds=.5,bounds=[1,2,21,13],model='model')));(self.folder/'delivery.json').write_text('{"state":"accepted_by_mail"}')
  self.message=dict(sender='Owner <owner@example.org>',subject='Re: Field station: anomalous candidate ['+'a'*12+']',content='no insect.\n\nOn Tuesday, station wrote:\n> yes',headers='In-Reply-To: <original@example.org>\nAuthentication-Results: mail.example.org; dkim=pass\n',message_id='reply@example.org',received_epoch=100,sent_message_ids=['original@example.org'])
 def tearDown(self):self.tmp.cleanup()
 def test_explicit_grammar(self):
  for text,wanted in [('mountain','mountain'),('mountains.','mountain'),('no mountain','mountain'),('telephone pole','telephone_pole'),('no telephone pole','telephone_pole'),('telephone poles.','telephone_pole'),('utility pole','telephone_pole'),('house','house'),('no house','house'),('houses.','house'),('antenna','antenna'),('antennas','antenna'),('no antenna','antenna'),('vehicle','vehicle'),('vehicles','vehicle'),('no vehicle','vehicle'),('car','vehicle'),('truck','vehicle'),('yes.','anomalous'),('YES!','anomalous'),('no insect.','insect'),('no airplane','airplane'),('no bird','bird'),('no cloud','cloud'),('no','not_anomalous'),('cloud','cloud'),('BIRD!','bird'),('airplane.','airplane'),('bug','insect'),('plane','airplane'),('other animal','other_animal'),('anomalous','anomalous'),('star','star'),('stars.','star'),('no star','star'),('no stars','star'),('satellite','satellite'),('satellites.','satellite'),('no satellite','satellite'),('shooting star','shooting_star'),('shooting stars.','shooting_star'),('meteor','shooting_star'),('no shooting star','shooting_star')]:self.assertEqual(parse_reply(text),wanted)
  for text in ['maybe yes','no unicorn','yes no insect','> yes','yes?','cloud?','cloud or bird','no anomalous','> cloud','probably cloud']:self.assertIsNone(parse_reply(text))
 def test_reply_enrolls_exact_crop_once_in_real_training_loader(self):
  self.assertEqual(ingest(self.message,self.config),'imported');self.assertEqual(ingest(self.message,self.config),'already_imported');rows=reviewed_examples(self.data);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],'insect');self.assertEqual(rows[0]['group'],'generation:run-a');self.assertEqual(rows[0]['image'].read_bytes(),(self.folder/'native-object.png').read_bytes())
 def test_bare_category_corrects_existing_label_in_training(self):
  ingest(dict(self.message,content='yes'),self.config)
  self.assertEqual(ingest(dict(self.message,content='cloud.\n\n> Reply YES',message_id='correction',received_epoch=200),self.config),'imported')
  rows=reviewed_examples(self.data);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],'cloud')
  r=json.loads((self.data/'email-reviews/examples'/self.key/'review.json').read_text());self.assertFalse(r['binary_anomalous']);self.assertTrue(r['multiclass_ready'])
 def test_star_reply_is_preserved_in_training(self):
  self.assertEqual(ingest(dict(self.message,content='stars.'),self.config),'imported')
  rows=reviewed_examples(self.data);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],'star')
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab/recognition'))
  from candidate_dataset import load_rows
  (self.data/'videos').mkdir();legacy=self.root/'legacy';legacy.mkdir();(legacy/'dataset.json').write_text(json.dumps(dict(review_signatures={'fixture':'reviewed'},samples=[],fingerprint='fixture')))
  rows,excluded,_=load_rows(self.data,legacy);self.assertEqual(rows[0]['label'],'star');self.assertEqual(excluded,[])
 def test_satellite_reply_is_preserved_in_training(self):
  self.assertEqual(ingest(dict(self.message,content='satellites.'),self.config),'imported')
  rows=reviewed_examples(self.data);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],'satellite')
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab/recognition'))
  from candidate_dataset import load_rows
  (self.data/'videos').mkdir();legacy=self.root/'legacy';legacy.mkdir();(legacy/'dataset.json').write_text(json.dumps(dict(review_signatures={'fixture':'reviewed'},samples=[],fingerprint='fixture')))
  rows,excluded,_=load_rows(self.data,legacy);self.assertEqual(rows[0]['label'],'satellite');self.assertEqual(excluded,[])
 def test_shooting_star_reply_is_preserved_in_training(self):
  self.assertEqual(ingest(dict(self.message,content='shooting star.'),self.config),'imported')
  rows=reviewed_examples(self.data);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],'shooting_star')
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab/recognition'))
  from candidate_dataset import load_rows
  (self.data/'videos').mkdir();legacy=self.root/'legacy';legacy.mkdir();(legacy/'dataset.json').write_text(json.dumps(dict(review_signatures={'fixture':'reviewed'},samples=[],fingerprint='fixture')))
  rows,excluded,_=load_rows(self.data,legacy);self.assertEqual(rows[0]['label'],'shooting_star');self.assertEqual(excluded,[])
 def test_house_antenna_vehicle_are_retained_for_training(self):
  for i,label in enumerate(('mountain','telephone_pole','house','antenna','vehicle'),start=1):
   with self.subTest(label=label):
    self.assertEqual(ingest(dict(self.message,content=label,message_id='label-'+label,received_epoch=1000+i),self.config),'imported')
    self.assertEqual(reviewed_examples(self.data)[0]['label'],label)
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab/recognition'))
  from candidate_dataset import load_rows
  (self.data/'videos').mkdir();legacy=self.root/'legacy';legacy.mkdir();(legacy/'dataset.json').write_text(json.dumps(dict(review_signatures={'fixture':'reviewed'},samples=[],fingerprint='fixture')))
  rows,excluded,_=load_rows(self.data,legacy);self.assertEqual(rows[0]['label'],'vehicle');self.assertEqual(excluded,[])
 def test_wrong_sender_unlinked_and_test_never_train(self):
  for change in [dict(sender='other@example.org'),dict(headers='In-Reply-To: <other>'),dict(content='maybe'),dict(headers='In-Reply-To: <original@example.org>\nAuthentication-Results: mail.example.org; dmarc=fail')]:self.assertNotEqual(ingest(dict(self.message,**change),self.config),'imported')
  self.assertEqual(reviewed_examples(self.data),[])
 def test_later_reply_corrects_label_without_duplicate_or_old_reversal(self):
  ingest(self.message,self.config);ingest(dict(self.message,message_id='later',received_epoch=200,content='yes.'),self.config);ingest(dict(self.message,message_id='older',received_epoch=150,content='no bird'),self.config)
  self.assertEqual([r['label'] for r in reviewed_examples(self.data)],['anomalous']);self.assertEqual(len(list((self.data/'email-reviews/history').glob('*.json'))),3)
 def test_plain_no_is_binary_negative_not_invented_class(self):
  ingest(dict(self.message,content='no'),self.config);self.assertEqual(reviewed_examples(self.data),[]);r=json.loads((self.data/'email-reviews/examples'/self.key/'review.json').read_text());self.assertFalse(r['binary_anomalous']);self.assertEqual(r['label'],'not_anomalous')
 def test_candidate_dataset_uses_explicit_email_label(self):
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab/recognition'))
  from candidate_dataset import load_rows
  ingest(self.message,self.config);(self.data/'videos').mkdir();legacy=self.root/'legacy';legacy.mkdir();(legacy/'dataset.json').write_text(json.dumps(dict(review_signatures={'fixture':'reviewed'},samples=[],fingerprint='fixture')))
  rows,excluded,fingerprint=load_rows(self.data,legacy);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],'insect');self.assertEqual(rows[0]['group'],'generation:run-a');self.assertEqual(rows[0]['native_width'],21)
if __name__=='__main__':unittest.main()

class PollTests(unittest.TestCase):
 def test_imported_ids_are_skipped_and_waiting_messages_remain_retryable(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  from reply_reviews import poll
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'email-reviews';(root/'history').mkdir(parents=True)
   (root/'scanned-message-ids.json').write_text(json.dumps(['new']))
   (root/'history/old.json').write_text(json.dumps({'source':'owner_email_reply','message_id':'old'}))
   messages=[dict(message_id='new',received_epoch=2),dict(message_id='pending',received_epoch=3)]
   with patch('reply_reviews.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(messages))) as run,patch('reply_reviews.ingest',side_effect=['imported','waiting_for_native_crop']):
    self.assertEqual(poll({'lab_data':tmp,'recipient':'owner@example.org'}),{'imported':1,'waiting_for_native_crop':1})
    self.assertEqual(json.loads(run.call_args.args[0][-1]),['old'])
   self.assertEqual(json.loads((root/'scanned-message-ids-category-replies.json').read_text()),['new','old'])
