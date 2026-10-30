import tempfile,threading,time,json,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from native_journal import NativeJournal
from spool_events import atomic
class JournalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.live=self.root/'live';self.live.mkdir();self.run=self.root/'run-a';self.run.mkdir();self.monitor=SimpleNamespace(stop_event=threading.Event(),state={});self.saved=[]
 def tearDown(self):self.monitor.stop_event.set();time.sleep(.12);self.tmp.cleanup()
 def record(self,n,generation='run-a'):
  timing=dict(sequence=n,pts_seconds=n/60,received_epoch=100+n/60);state=dict(generation=generation,last_sequence=n,last_pts_seconds=n/60,analyzed_epoch=time.time(),generation_analyzed_frames=n+1,generation_missing_frames=0,analyzed_frames=n+1)
  return timing,[[2,2,4,4]],{},generation,None,state
 def test_acknowledgment_follows_ordered_evidence_writes(self):
  writer=NativeJournal(self.root,self.live,self.monitor,self.saved.append);writer.start()
  for i in range(3):writer.submit(self.record(i))
  writer.flush();ack=json.loads((self.run/'analysis-ack.json').read_text());self.assertEqual(ack['last_sequence'],2);event=json.loads((self.run/'open-event.json').read_text());rows=[json.loads(s) for s in (self.run/'candidates'/(event['session_id']+'.jsonl')).read_text().splitlines()];self.assertEqual([r['sequence'] for r in rows],[0,1,2]);self.assertEqual(self.saved[-1]['last_sequence'],2)
 def test_full_queue_blocks_without_replacing_a_record(self):
  writer=NativeJournal(self.root,self.live,self.monitor,self.saved.append,capacity=1);writer.submit(self.record(0));done=threading.Event()
  def submit():writer.submit(self.record(1));done.set()
  worker=threading.Thread(target=submit);worker.start();self.assertFalse(done.wait(.15));self.assertEqual(writer.pending.get()[0]['sequence'],0);self.assertTrue(done.wait(1));self.assertEqual(writer.pending.get()[0]['sequence'],1);worker.join()
 def test_generation_completes_only_after_final_consumer_record(self):
  writer=NativeJournal(self.root,self.live,self.monitor,self.saved.append)
  for i in range(3):writer.process(self.record(i))
  self.assertFalse((self.run/'analysis-complete.json').exists());atomic(self.run/'closed.json',{});atomic(self.run/'capture-health.json',dict(captured_frames=3));(self.root/'run-b').mkdir();writer.process(self.record(0,'run-b'))
  self.assertEqual(json.loads((self.run/'analysis-complete.json').read_text())['last_sequence'],2);self.assertFalse((self.run/'open-event.json').exists());self.assertEqual(len(list((self.run/'events').glob('*.json'))),1)
 def test_journal_failure_resumes_from_last_durable_checkpoint(self):
  writer=NativeJournal(self.root,self.live,self.monitor,self.saved.append);writer.process(self.record(0));writer.process(self.record(1));self.assertEqual(writer.committed['last_sequence'],0)
  with patch.object(writer.events,'update',side_effect=OSError('disk failure')):
   writer.start();writer.submit(self.record(2));self.assertTrue(self.monitor.stop_event.wait(2))
  fault=json.loads((self.live/'native-analysis.json').read_text());self.assertEqual(fault['last_sequence'],0);self.assertEqual(fault['phase'],'journal_error')
 def test_restart_at_generation_boundary_finishes_pending_event(self):
  writer=NativeJournal(self.root,self.live,self.monitor,self.saved.append)
  for i in range(3):writer.process(self.record(i))
  writer.persist();atomic(self.run/'closed.json',{});atomic(self.run/'capture-health.json',dict(captured_frames=3));(self.root/'run-b').mkdir()
  recovered=NativeJournal(self.root,self.live,self.monitor,self.saved.append);recovered.process(self.record(0,'run-b'))
  self.assertFalse((self.run/'open-event.json').exists());self.assertEqual(len(list((self.run/'events').glob('*.json'))),1);self.assertEqual(json.loads((self.run/'analysis-complete.json').read_text())['last_sequence'],2)
