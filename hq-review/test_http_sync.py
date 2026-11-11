import base64,json,gzip,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from store import Store
from sync import Sync
from server import Server,Handler
FRAME=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=')
class Field(BaseHTTPRequestHandler):
 def send(self,value,mime='application/json'):
  raw=value if isinstance(value,bytes) else json.dumps(value).encode();self.send_response(200)
  if mime=='application/json' and 'gzip' in self.headers.get('Accept-Encoding',''):raw=gzip.compress(raw);self.send_header('Content-Encoding','gzip')
  self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  self.server.paths.append(self.path)
  if self.path=='/api/labeled-frames/token':self.send(dict(token='field-token'))
  elif self.path=='/api/hq/snapshot':self.send(dict(schema=1,complete=True,items=[dict(id='a'*32,label='anomalous',human_reviewed=False,review_revision='unreviewed',created=1,image_url='/api/label-queue/image?id='+('a'*32),frame_url='/api/label-queue/image?full=1&id='+('a'*32))]))
  else:self.send(FRAME,'image/png')
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.server.received.extend(body['items']);self.send(dict(results=[dict(request_id=i['request_id'],id=i['id'],label=i['label'],state='synced',review_revision='field-revision') for i in body['items']]))
 def log_message(self,*args):pass
class Integration(unittest.TestCase):
 def launch(self,server):
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown);return 'http://127.0.0.1:'+str(server.server_port)
 def test_browser_offline_save_and_reconnection(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(d);field=ThreadingHTTPServer(('127.0.0.1',0),Field);field.paths=[];field.received=[];origin=self.launch(field);worker=Sync(store,origin);worker.cycle();self.assertEqual(store.summary()['cached_frames'],1)
   hq=Server(('127.0.0.1',0),Handler);hq.store=store;url=self.launch(hq)
   def request(path,body=None,token='',origin_override=None):
    headers={'X-HQ-Token':token,'Origin':origin_override or url,'Content-Type':'application/json'}
    with urllib.request.urlopen(urllib.request.Request(url+path,data=json.dumps(body).encode() if body else None,headers=headers)) as r:return json.load(r)
   token=request('/api/status')['token'];body=dict(ids=['a'*32],label='not_anomalous',reviewer='HQ test',revisions={'a'*32:'unreviewed'})
   with self.assertRaises(urllib.error.HTTPError) as e:request('/api/review',body,token,'http://untrusted.example')
   self.assertEqual(e.exception.code,403)
   request('/api/review',body,token);self.assertEqual(field.received,[]);self.assertEqual(request('/api/objects?review=needs_review')['total'],0)
   with self.assertRaises(urllib.error.HTTPError):request('/api/review',dict(body,label='anomalous'),token)
   original=worker.origin;worker.origin='http://127.0.0.1:1';worker.cycle();self.assertEqual(request('/api/status')['decisions']['pending'],1)
   with urllib.request.urlopen(url+'/api/image?id='+('a'*32)) as response:self.assertEqual(response.read(),FRAME)
   worker.origin=original;worker.cycle();self.assertEqual(len(field.received),1);self.assertEqual(field.received[0]['reviewer'],'HQ test');self.assertEqual(request('/api/status')['decisions']['synced'],1)
   self.assertFalse(any('video' in path for path in field.paths))
if __name__=='__main__':unittest.main()
