import http.client,json,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from readonly import Server,clean,state_snapshot
class Upstream(BaseHTTPRequestHandler):
 calls=[]
 def do_GET(self):
  self.calls.append(self.path)
  if self.path=='/':body=b'<html><head></head><body>Existing Field Station</body></html>';mime='text/html'
  elif self.path=='/ufo-no-signal.png':body=b'\x89PNG\r\n\x1a\nfixture';mime='image/png'
  else:body=json.dumps(dict(token='DO-NOT-EXPOSE',nested=dict(csrf='DO-NOT-EXPOSE',path='/Users/private/file'),original_available=True,ready=True)).encode();mime='application/json'
  self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
class ReadOnlyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.up=ThreadingHTTPServer(('127.0.0.1',0),Upstream);threading.Thread(target=self.up.serve_forever,daemon=True).start();Upstream.calls=[]
  self.server=Server(('127.0.0.1',0),self.up.server_port,self.root,Path(__file__).parent);threading.Thread(target=self.server.serve_forever,daemon=True).start()
 def tearDown(self):
  for s in (self.server,self.up):s.shutdown();s.server_close()
  self.temp.cleanup()
 def get(self,path,method='GET',headers=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3);c.request(method,path,headers=headers or {});r=c.getresponse();b=r.read();c.close();return r.status,b
 def test_existing_ui_preserved(self):
  code,body=self.get('/');self.assertEqual(code,200);self.assertIn(b'Existing Field Station',body);self.assertIn(b'/public-readonly.js',body)
 def test_no_signal_artwork_allowed_without_opening_other_images(self):
  code,body=self.get('/ufo-no-signal.png?v=1');self.assertEqual(code,200);self.assertTrue(body.startswith(b'\x89PNG'))
  self.assertEqual(self.get('/private.png')[0],404)
  self.assertEqual(self.get('/elgato-no-signal-reference.jpg')[0],404)
  self.assertEqual(Upstream.calls,['/ufo-no-signal.png'])
 def test_writes_never_reach_upstream(self):
  for method in ('POST','PUT','PATCH','DELETE','CONNECT','TRACE'):
   self.assertEqual(self.get('/api/live/start',method)[0],405)
  self.assertEqual(Upstream.calls,[])
 def test_video_and_decoding_blocked_including_ranges_and_head(self):
  for path in ('/api/video?id='+'a'*32,'/api/email-review/video?id='+'a'*32,'/api/live/artifact?session=x&name=video.mp4','/api/frame?id=x&time=1','/api/label-queue/video-image?id=x','/api/timeline?id=x','/api/recognition/proposals?id=x','/results/a/video.mp4','/email-review?id=x'):
   for method in ('GET','HEAD'):
    self.assertEqual(self.get(path,method,{'Range':'bytes=0-100'})[0],404,path)
  self.assertEqual(Upstream.calls,[])
 def test_no_credentials_or_private_paths(self):
  code,body=self.get('/api/live/status');self.assertEqual(code,200)
  for secret in (b'DO-NOT-EXPOSE',b'/Users/private',b'csrf',b'token'):self.assertNotIn(secret,body)
  self.assertFalse(json.loads(body)['original_available'])
  self.assertNotIn(b'token',self.get('/api/labeled-frames/token')[1])
 def test_shared_status_cache_reduces_upstream_requests(self):
  self.get('/api/live/status');self.get('/api/live/status')
  self.assertEqual(Upstream.calls,['/api/live/status'])
 def test_no_arbitrary_proxy_or_query_forward(self):
  for path in ('http://example.com/api/live/status','/../environment.json','/api/live/status?url=http://example.com','/api/labeled-frames?limit=999999','/api/labeled-frames?limit=1&limit=2'):
   self.assertIn(self.get(path)[0],(400,404))
  self.assertEqual(Upstream.calls,[])
 def test_state_snapshot_cannot_reconcile_or_write(self):
  folder=self.root/'uap-lab/videos'/('a'*32);folder.mkdir(parents=True)
  (folder/'video.json').write_text(json.dumps(dict(id='a'*32,sha256='hash',created=1)))
  (folder/'review.json').write_text('{"completed":true}')
  before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  result=state_snapshot(self.root)
  self.assertEqual(result['videos'],[])
  after={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  self.assertEqual(before,after)
if __name__=='__main__':unittest.main()
