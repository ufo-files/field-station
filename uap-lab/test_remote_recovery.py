import io,json,tarfile,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import lab,remote_evaluation as remote
class RecoveryTests(unittest.TestCase):
 def test_completed_remote_job_is_not_resubmitted(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);rid='a'*32;folder=root/'runs'/rid;folder.mkdir(parents=True);cfg=root/'worker.json';cfg.write_text(json.dumps(dict(known_hosts='/pinned',identity='/key',username='worker',host='m6')))
   actions=[]
   def rpc(*args,**kwargs):
    req=json.loads(kwargs['input']);actions.append(req['action']);return SimpleNamespace(returncode=0,stdout=json.dumps(dict(ready=True) if req['action']=='ping' else dict(state='complete',frame_count=10,detected_frames=0)).encode())
   stream=io.BytesIO()
   with tarfile.open(fileobj=stream,mode='w:gz'):pass
   class Process:
    def __init__(self,*args,**kwargs):self.stdin=io.BytesIO();self.stdout=io.BytesIO(stream.getvalue())
    def wait(self):return 0
   with patch.object(lab,'DATA',root),patch.dict(remote.os.environ,{'UAP_LAB_WORKER_CONFIG':str(cfg)}),patch.object(remote.subprocess,'run',side_effect=rpc),patch.object(remote.subprocess,'Popen',Process):
    remote.evaluate(rid,'b'*32,dict(id='c'*32),.97,['anomalous'])
   self.assertEqual(actions,['ping','status','status']);self.assertEqual(lab.read(folder/'run.json')['state'],'complete')
