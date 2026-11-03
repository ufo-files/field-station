import http.client, json, tempfile, threading, unittest
from pathlib import Path
from dashboard import Server, Handler, Exporter, safe_file

class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.output=self.root/'public';self.output.mkdir();self.static=self.root/'static';self.static.mkdir()
        (self.static/'index.html').write_text('public viewer');(self.root/'secret').write_text('token-secret')
        (self.output/'status.json').write_text('{"ready": true}')
        (self.root/'video.mp4').write_bytes(b'0123456789')
        (self.output/'media-map.json').write_text(json.dumps({'a'*64:'video.mp4','b'*64:'escape.mp4'}))
        (self.root/'escape.mp4').symlink_to('/etc/hosts')
        self.server=Server(('127.0.0.1',0),Handler,self.root,self.output,self.static)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def request(self,path,method='GET',headers=None):
        conn=http.client.HTTPConnection(*self.server.server_address,timeout=3)
        conn.request(method,path,headers=headers or {});res=conn.getresponse();body=res.read();conn.close();return res.status,body,dict(res.getheaders())
    def test_control_and_private_routes_absent(self):
        for p in ('/api/state','/api/email-review','/api/labeled-frames/token','/media-map.json','/secret','/../secret','/%2e%2e/secret','//etc/hosts'):
            self.assertEqual(self.request(p)[0],404,p)
    def test_mutations_rejected(self):
        for method in ('POST','PUT','PATCH','DELETE','OPTIONS','CONNECT','TRACE'):
            self.assertEqual(self.request('/status.json',method)[0],405)
    def test_range_and_head(self):
        code,body,headers=self.request('/media/'+'a'*64,headers={'Range':'bytes=2-5'})
        self.assertEqual((code,body),(206,b'2345'));self.assertEqual(headers['Content-Range'],'bytes 2-5/10')
        self.assertEqual(self.request('/media/'+'a'*64,'HEAD')[1],b'')
        for value in ('bytes=20-30','bytes=0-1,3-4','bytes=-0','bytes=a-b'):
            self.assertEqual(self.request('/media/'+'a'*64,headers={'Range':value})[0],416)
    def test_symlink_and_removed_media(self):
        self.assertEqual(self.request('/media/'+'b'*64)[0],404)
        (self.root/'video.mp4').unlink();self.assertEqual(self.request('/media/'+'a'*64)[0],404)
    def test_catalog_does_not_export_private_metadata(self):
        folder=self.root/'sessions/20261103T120000Z-abcdef';folder.mkdir(parents=True)
        (folder/'video.mp4').write_bytes(b'video')
        (folder/'manifest.json').write_text(json.dumps(dict(state='completed',started_epoch=1,elapsed_seconds=3,token='secret',error='/Users/private',title='private title')))
        e=Exporter(self.root,self.output);e.catalog_update();raw=(self.output/'recordings.json').read_text()
        for private in ('token','/Users','private title'): self.assertNotIn(private,raw)
        self.assertEqual(len(json.loads(raw)),1)
    def test_security_headers(self):
        code,_,headers=self.request('/')
        self.assertEqual(code,200);self.assertIn("form-action 'none'",headers['Content-Security-Policy'])
        self.assertNotIn('Python',headers['Server'])
if __name__=='__main__': unittest.main()
