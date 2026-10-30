import tempfile,unittest,json,time
from pathlib import Path
from unittest.mock import patch
import lab
from spool_events import atomic
from spool_export import export_event
class ExportTests(unittest.TestCase):
 def test_delayed_export_keeps_native_video_timing_rf_and_complete_context(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);run=root/'run-abcdef';run.mkdir();station=root/'station';(station/'sessions').mkdir(parents=True)
   segments=[]
   for i in range(31):
    name=f'segment-{i:09d}.mkv';(run/name).write_bytes(b'native'+bytes([i]));segments.append(dict(file=name,start=i,end=i+1,start_epoch=1000+i,end_epoch=1001+i,bytes=7,sha256='hash'))
    (run/f'frame-times-{i:09d}.jsonl').write_text(json.dumps(dict(sequence=i,pts_seconds=i))+'\n')
   (run/'segments-index.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in segments));(run/'rf.jsonl').write_text(''.join(json.dumps(dict(captured_epoch=1000+i,spectrum={'receivers':{'narrow':{},'wide':{}}}))+'\n' for i in range(31)))
   event=dict(session_id='20261029T200000Z-abcdef',generation=run.name,start_pts=10,end_pts=30,onset_pts=20,frame_epoch=1020,created=time.time(),state='ready',model_id='a'*32);path=run/'events/event.json';atomic(path,event)
   with patch.object(lab,'STATION',station):export_event(root,path)
   folder=station/'sessions'/event['session_id'];m=lab.read(folder/'manifest.json');self.assertEqual(m['pre_roll_actual_seconds'],10);self.assertTrue(m['pre_roll_complete']);self.assertEqual(m['rf_records'],21);self.assertEqual(len(list((folder/'buffer-segments').glob('*.mkv'))),20);self.assertEqual(lab.read(path)['state'],'exported')
   self.assertEqual((folder/'buffer-segments/segment-000000010.mkv').read_bytes(),(run/'segment-000000010.mkv').read_bytes())
