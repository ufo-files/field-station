import json,tempfile,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from observation_metrics import TZ,daylight,summarize,merged,contains,build

def epoch(value):return datetime.fromisoformat(value).timestamp()
class MetricsTests(unittest.TestCase):
 def test_sunrise_sunset_boundaries_and_unknown_audio(self):
  day=datetime(2026,11,7).date();rise,setting=daylight(day)
  values=summarize([rise-1,rise,setting-1,setting,None],[[rise,rise+10]],[[rise-10,setting+10]],setting+100,1)
  self.assertEqual(values['total'],4);self.assertEqual(values['daytime'],2);self.assertEqual(values['nighttime'],2)
  self.assertEqual(values['ce5_on'],1);self.assertEqual(values['ce5_off'],3);self.assertEqual(values['missing_time'],1)
  older=summarize([rise],[],[],setting+100,1);self.assertEqual(older['ce5_unknown'],1);self.assertEqual(older['ce5_off'],0)
 def test_capture_hour_dst_and_period_filter(self):
  first=epoch('2026-11-01T01:30:00-07:00');second=epoch('2026-11-01T01:30:00-08:00')
  values=summarize([first,second,second-90000],[],[],second+1,1)
  self.assertEqual(values['total'],2);self.assertEqual(values['hours'][1]['total'],2)
 def test_interval_union_and_half_open_boundary(self):
  spans=merged([(1,3),(2,5),(5,6),(7,8),(9,9)])
  self.assertEqual(spans,[[1,6],[7,8]]);self.assertTrue(contains(spans,1));self.assertFalse(contains(spans,6))
 def test_reviewed_objects_use_capture_time_not_review_time(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);data=root/'uap-lab';reviews=data/'email-reviews';reviews.mkdir(parents=True)
   key='a'*32;stamp=epoch('2026-11-07T12:00:00-08:00');out=root/'notifications/outbox'/key;out.mkdir(parents=True)
   (out/'event.json').write_text(json.dumps(dict(detected_epoch=stamp,created_epoch=stamp+7200)))
   records=[dict(event_id=key,sample_id=c*32,label='anomalous',human_confirmed=True,reviewed_epoch=stamp+36000) for c in ['b','c']]
   (reviews/'training-manifest.json').write_text(json.dumps(dict(examples=records)))
   rows=[dict(id='review:'+key+':'+c*32,video_id=key,sample_id=c*32,kind='review',label='anomalous',human_reviewed=True) for c in ['b','c']]
   with patch('observation_metrics.library_rows',return_value=rows),patch('observation_metrics.time.time',return_value=stamp+10):
    result=build(data)
   human=result['scopes']['human']['0'];self.assertEqual(human['total'],2);self.assertEqual(human['hours'][12]['total'],2)
   self.assertEqual(human['ce5_unknown'],2)

 def test_training_imports_are_not_station_observations(self):
  from observation_metrics import station_video
  self.assertFalse(station_video({'provenance':{'collection':'PURSUE'}}))
  self.assertFalse(station_video({'name':'uploaded-training-video.mp4'}))
  self.assertTrue(station_video({'provenance':{'session_id':'20261107T101249Z-4fa25c'}}))
 def test_unknown_capture_time_all_history_only(self):
  self.assertEqual(summarize([None],[],[],1000,0)['total'],1)
  self.assertEqual(summarize([None],[],[],1000,30)['total'],0)

 def test_human_corrections_replace_machine_flags(self):
  from observation_metrics import library_rows
  with tempfile.TemporaryDirectory() as directory:
   data=Path(directory)/'uap-lab';reviews=data/'email-reviews';reviews.mkdir(parents=True)
   a,b,c='a'*32,'b'*32,'c'*32
   records=[dict(event_id=a,sample_id=a,label='not_anomalous',human_confirmed=True),dict(event_id=c,sample_id=c,label='anomalous',human_confirmed=True)]
   (reviews/'training-manifest.json').write_text(json.dumps(dict(examples=records)))
   cached=[dict(id=key,kind='detection',label='anomalous',human_reviewed=False,created=100) for key in [a,b,c]]
   with patch('detection_library.refresh',return_value=((1,cached),False,None)),patch('recognition.recognition_alerts.recent_detections',return_value=([],False)):
    rows=library_rows(data)
   humans=[row['id'] for row in rows if row['human_reviewed'] and row['label']=='anomalous']
   machines=[row['id'] for row in rows if not row['human_reviewed'] and row['label']=='anomalous']
   self.assertEqual(humans,[c]);self.assertEqual(machines,[b])

class FalsePositiveTests(unittest.TestCase):
 def test_denominators_missing_history_and_gaps(self):
  from observation_metrics import false_positive_history
  first=epoch('2026-11-01T12:00:00-08:00');last=epoch('2026-11-03T12:00:00-08:00')
  objects=[(first,'anomalous','not_anomalous'),(first,'not_anomalous','not_anomalous'),(first,'anomalous','anomalous'),(first,'not_anomalous','anomalous'),(first,None,'not_anomalous'),(None,'anomalous','not_anomalous'),(last,'anomalous','anomalous')]
  result=false_positive_history(objects,last+1,0)
  self.assertEqual(result['rate'],.5);self.assertEqual(result['false_alarm_share'],1/3)
  self.assertEqual(result['reviewed'],5);self.assertEqual(result['missing_prediction'],1);self.assertEqual(result['missing_time'],1)
  self.assertEqual(len(result['points']),3);self.assertIsNone(result['points'][1]['rate']);self.assertIsNone(result['points'][2]['rate'])
  filtered=false_positive_history(objects,last+1,1);self.assertEqual(filtered['reviewed'],1);self.assertIsNone(filtered['rate'])
 def test_original_prediction_is_not_inherited_by_manual_crops(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);data=root/'uap-lab';data.mkdir();key='a'*32;out=root/'notifications/outbox'/key;out.mkdir(parents=True)
   stamp=epoch('2026-11-07T12:00:00-08:00')
   (out/'event.json').write_text(json.dumps(dict(detected_epoch=stamp,classification='anomalous')))
   rows=[dict(id=key,kind='review',video_id=key,sample_id=key,label='not_anomalous',human_reviewed=True),dict(id='review:'+key+':'+'b'*32,kind='review',video_id=key,sample_id='b'*32,label='not_anomalous',human_reviewed=True)]
   with patch('observation_metrics.library_rows',return_value=rows),patch('observation_metrics.time.time',return_value=stamp+10):result=build(data)
   values=result['false_positives']['0'];self.assertEqual(values['fp'],1);self.assertEqual(values['missing_prediction'],1);self.assertEqual(result['scopes']['human']['0']['total'],0)
