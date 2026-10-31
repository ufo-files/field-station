import http.client,json,os,tempfile,threading,time,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from web_frontend import server
class Backend(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=='/api/service-health':data=b'{"ready":true,"instance":"one"}';status=200
  elif self.headers.get('Range'):data=b'abc';status=206
  else:data=b'working';status=200
  self.send_response(status);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_POST(self):
  data=self.rfile.read(int(self.headers['Content-Length']));self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
class FrontendTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.marker=Path(self.tmp.name)/'marker.json'
  self.backend=ThreadingHTTPServer(('127.0.0.1',0),Backend);threading.Thread(target=self.backend.serve_forever,daemon=True).start()
  self.front=server(0,self.backend.server_port,self.marker,Path(__file__).parent/'static');threading.Thread(target=self.front.serve_forever,daemon=True).start()
 def tearDown(self):
  self.front.shutdown();self.front.server_close();self.backend.shutdown();self.backend.server_close();self.tmp.cleanup()
 def request(self,path='/',method='GET',body=None,headers={}):
  c=http.client.HTTPConnection('127.0.0.1',self.front.server_port,timeout=5);c.request(method,path,body,headers);r=c.getresponse();out=(r.status,r.read());c.close();return out
 def test_range_upload_and_health_forwarding(self):
  self.assertEqual(self.request('/video',headers={'Range':'bytes=0-2'}),(206,b'abc'))
  self.assertEqual(self.request('/api/save','POST',b'labels'),(200,b'labels'))
  self.assertTrue(json.loads(self.request('/api/service-status')[1])['available'])
 def test_cleanup_blocks_mutations_but_serves_screen_and_recovers(self):
  self.marker.write_text(json.dumps(dict(pid=os.getpid(),started_epoch=time.time())))
  self.assertIn(b'Field Station',self.request('/email-review?id=abc')[1])
  self.assertEqual(self.request('/api/save','POST',b'labels')[0],503)
  self.assertEqual(json.loads(self.request('/api/service-status')[1])['phase'],'cleanup')
  self.assertEqual(self.request('/maintenance.js')[0],200)
  self.marker.unlink();self.assertEqual(self.request(),(200,b'working'))
 def test_unplanned_restart_and_stale_marker(self):
  self.marker.write_text(json.dumps(dict(pid=os.getpid(),started_epoch=time.time()-2000)))
  self.assertTrue(json.loads(self.request('/api/service-status')[1])['available'])
  self.backend.shutdown();self.backend.server_close()
  self.assertIn(b'Checking station status',self.request('/tracks')[1])
  self.assertEqual(json.loads(self.request('/api/service-status')[1])['phase'],'reconnecting')
if __name__=='__main__':unittest.main()
