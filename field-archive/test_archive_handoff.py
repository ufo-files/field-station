import hashlib,json,tarfile,tempfile,unittest
from pathlib import Path
from archive_handoff import release_cached_archive,fingerprint,digest
from archive_bridge import member,package
class HandoffTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.archive=self.root/'archive';self.archive.mkdir();self.sessions=self.root/'sessions';self.sid='20261109T000000Z-abcdef';session=self.sessions/self.sid;session.mkdir(parents=True);self.meta=session/'manifest.json';self.meta.write_text(json.dumps(dict(capture_origin='provisional_motion')))
  self.video=session/'video.mkv';self.video.write_bytes(b'original capture');self.name='sessions/'+self.sid+'/video.mkv';self.unit=dict(session=self.sid,files=[dict(path=self.name,bytes=self.video.stat().st_size,sha256=digest(self.video))]);self.key=fingerprint(self.unit);self.folder=self.archive/self.key;self.folder.mkdir();self.tar=self.folder/'recording.tar'
  with tarfile.open(self.tar,'w') as t:t.add(self.video,arcname=self.name)
  (self.folder/'manifest.json').write_text(json.dumps(self.unit));(self.folder/'receipt.json').write_text(json.dumps(dict(verified=True,fingerprint=self.key)))
  self.proof=dict(verified_at=1,hashes={'recording.tar':digest(self.tar)});(self.folder/'.replica-receipt.json').write_text(json.dumps(self.proof))
 def tearDown(self):self.tmp.cleanup()
 def test_verified_automatic_cache_can_be_released(self):
  result=release_cached_archive(self.archive,self.sessions,self.key,self.proof,self.unit,'http://private/v1/'+self.key)
  self.assertGreater(result['bytes'],0);self.assertFalse(self.tar.exists());self.assertTrue((self.folder/'remote-copy.json').exists());self.assertTrue(self.video.exists())
 def test_manual_is_never_evicted(self):
  self.meta.write_text(json.dumps(dict(capture_origin='manual')))
  with self.assertRaisesRegex(ValueError,'protected'):release_cached_archive(self.archive,self.sessions,self.key,self.proof,self.unit,'private')
  self.assertTrue(self.tar.exists())
 def test_corrupt_cache_is_not_evicted(self):
  self.tar.write_bytes(b'changed')
  with self.assertRaises(ValueError):release_cached_archive(self.archive,self.sessions,self.key,self.proof,self.unit,'private')
  self.assertTrue(self.tar.exists())
 def test_wrong_remote_identity_is_not_evicted(self):
  with self.assertRaises(ValueError):release_cached_archive(self.archive,self.sessions,self.key,self.proof,dict(session='wrong'),'private')
  self.assertTrue(self.tar.exists())
 def test_bridge_reads_only_verified_indexed_members(self):
  t,f,e=member(self.archive,self.key,self.name)
  with t,f:self.assertEqual(f.read(),b'original capture')
  with self.assertRaises(ValueError):member(self.archive,self.key,'../secret')
  (self.folder/'.replica-receipt.json').write_text('{}')
  with self.assertRaises(ValueError):package(self.archive,self.key)

 def test_http_bridge_requires_auth_and_returns_exact_original(self):
  import threading,urllib.request,urllib.error
  from http.server import ThreadingHTTPServer
  from unittest.mock import patch
  from archive_bridge import handler
  with patch.object(Path,'is_mount',return_value=True):
   server=ThreadingHTTPServer(('127.0.0.1',0),handler(dict(volume=str(self.root),root=str(self.archive),token='test-secret')))
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    url='http://127.0.0.1:'+str(server.server_port)+'/v1/'+self.key+'/'
    with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(url+'manifest.json')
    self.assertEqual(caught.exception.code,403)
    request=urllib.request.Request(url+self.name,headers={'Authorization':'Bearer test-secret'})
    with urllib.request.urlopen(request) as response:self.assertEqual(response.read(),b'original capture')
   finally:server.shutdown();server.server_close();thread.join()
