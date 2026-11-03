#!/usr/bin/env python3
"""Read-only entry point for the existing Field Station app, not a replacement UI."""
import argparse, http.client, json, math, os, re, shutil, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, urlencode

PAGES={'/','/metrics','/label-videos','/tracks','/labels','/events','/training'}
ASSETS={'/'+name+ext for name in ('app','app-shell','style','metrics','label-videos','tracks','labels','events','email-review','maintenance') for ext in ('.js','.css')}
ASSETS.add('/ufo-no-signal.png')
JSON_ROUTES={
 '/api/service-status':set(), '/api/service-health':set(), '/api/state':set(),
 '/api/model-metrics':set(), '/api/training-history':set(), '/api/training-control':set(),
 '/api/live/status':set(), '/api/live/session':set(), '/api/live/rf':set(),
 '/api/recognition/status':set(), '/api/model-publication/status':set(), '/api/provisional':set(),
 '/api/labeled-frames':{'label','search','offset','limit','video'},
 '/api/label-queue':{'source','before','limit'}, '/api/tracks':{'id'},
 '/api/review-progress':{'id'},
 '/api/live/artifact-status':{'session'}, '/api/labeled-frames/token':set(),
}
MEDIA_ROUTES={
 '/api/live/frame':{'t'},
 '/api/annotation':{'id','annotation'}, '/api/labeled-image':{'source','id','annotation'},
 '/api/label-queue/image':{'id','full'},

}
PRIVATE=re.compile(r'token|csrf|password|secret|credential|authorization|cookie|recipient|email_address',re.I)
PATHS=re.compile(r'/(?:Users|Volumes|home)/[^\s"\'<>]*')

def clean(value):
 if isinstance(value,dict):
  value=dict(value)
  if 'original_available' in value:value['original_available']=False
  value.pop('review_url',None)
  return {k:('Details unavailable publicly' if k=='error' and v else clean(v)) for k,v in value.items() if not PRIVATE.search(k)}
 if isinstance(value,list):return [clean(v) for v in value]
 if isinstance(value,str):return PATHS.sub('[private path]',value)
 if isinstance(value,float) and not math.isfinite(value):return None
 return value

def read(path,default=None):
 try:
  if path.is_symlink() or path.stat().st_size>32*1024*1024:return default
  return json.loads(path.read_text())
 except (OSError,ValueError):return default

def state_snapshot(root):
 # Camera initialization needs the model and labels, not a video-library scan.
 data=root/'uap-lab'
 return dict(read_only=True,labels=['anomalous','not_anomalous'],videos=[],runs=[],model=read(data/'active-model.json'),free_bytes=shutil.disk_usage(root).free,publication={})


def validated(path,query):
 allowed=JSON_ROUTES.get(path,MEDIA_ROUTES.get(path))
 if allowed is None:raise ValueError()
 q=parse_qs(query,keep_blank_values=True,max_num_fields=12)
 if set(q)-allowed or any(len(v)!=1 or len(v[0])>512 or '\x00' in v[0] or '\r' in v[0] or '\n' in v[0] for v in q.values()):raise ValueError()
 q={k:v[0] for k,v in q.items()}
 for key in ('limit','offset','after'):
  if key in q:
   n=int(q[key]);lo=-1 if key=='after' else 0
   if not lo<=n<=10000000 or (key=='limit' and not 1<=n<=100):raise ValueError()
 if 'time' in q and (not math.isfinite(float(q['time'])) or not 0<=float(q['time'])<=86400):raise ValueError()
 if path=='/api/label-queue' and q.get('source','detections')!='detections':raise ValueError()
 return q

class Server(ThreadingHTTPServer):
 daemon_threads=True
 request_queue_size=16
 def __init__(self,address,upstream,root,assets):
  self.upstream=upstream;self.root=root;self.assets=assets;self.device=root.stat().st_dev
  self.slots=threading.BoundedSemaphore(16);self.state_lock=threading.Lock();self.state_time=0;self.state=None
  self.cache={};self.cache_lock=threading.Lock();self.upstream_slots=threading.BoundedSemaphore(3)
  super().__init__(address,Handler)
 def process_request(self,request,address):
  if not self.slots.acquire(False):request.close();return
  try:super().process_request(request,address)
  except Exception:self.slots.release();raise
 def process_request_thread(self,request,address):
  try:super().process_request_thread(request,address)
  finally:self.slots.release()

class Handler(BaseHTTPRequestHandler):
 server_version='FieldStation';sys_version=''
 def setup(self):super().setup();self.connection.settimeout(20)
 def log_message(self,*args):pass
 def end_headers(self):
  self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff')
  self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
  super().end_headers()
 def send(self,body,status=200,mime='application/json'):
  self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers()
  if self.command!='HEAD':self.wfile.write(body)
 def json(self,value,status=200):self.send(json.dumps(clean(value),allow_nan=False).encode(),status)
 def reject(self):self.close_connection=True;self.json({'error':'Public access is read only.'},405)
 do_POST=do_PUT=do_PATCH=do_DELETE=do_TRACE=do_OPTIONS=do_CONNECT=reject
 def cache_response(self,key,body,mime,ttl):
  if len(body)>8*1024*1024:return
  with self.server.cache_lock:
   now=time.monotonic()
   self.server.cache={k:v for k,v in self.server.cache.items() if v[0]>now}
   while self.server.cache and (len(self.server.cache)>=64 or sum(len(v[1]) for v in self.server.cache.values())+len(body)>16*1024*1024):
    del self.server.cache[next(iter(self.server.cache))]
   self.server.cache[key]=(now+ttl,body,mime)
 def do_HEAD(self):self.do_GET()
 def do_GET(self):
  connection=None;acquired=False
  try:
   if self.server.root.stat().st_dev!=self.server.device:self.json({'error':'Station storage unavailable'},503);return
   u=urlsplit(self.path);path=u.path
   if u.scheme or u.netloc or len(self.path)>2048:self.json({'error':'Invalid request'},400);return
   if path in ('/public-readonly.js','/public-readonly.css'):
    f=self.server.assets/path[1:];self.send(f.read_bytes(),mime='text/javascript' if f.suffix=='.js' else 'text/css');return
   if path=='/api/labeled-frames/token':self.json({'read_only':True});return
   if path in PAGES or path in ASSETS:target=path
   elif path in JSON_ROUTES or path in MEDIA_ROUTES:
    q=validated(path,u.query);target=path+('?' + urlencode(q) if q else '')
    if path=='/api/state':
     with self.server.state_lock:
      if time.monotonic()-self.server.state_time>10:
       self.server.state=state_snapshot(self.server.root);self.server.state_time=time.monotonic()
      result=self.server.state
     self.json(result);return
   else:self.json({'error':'Not found'},404);return
   cache_key=path if path=='/api/live/frame' else target
   with self.server.cache_lock:
    cached=self.server.cache.get(cache_key)
   if cached and time.monotonic()<cached[0]:
    self.send(cached[1],mime=cached[2]);return
   if not self.server.upstream_slots.acquire(timeout=15):
    self.json({'error':'Station viewer is busy. Retry shortly.'},503);return
   acquired=True
   connection=http.client.HTTPConnection('127.0.0.1',self.server.upstream,timeout=20)
   headers={}
   if path in MEDIA_ROUTES and self.headers.get('Range'):
    if not re.fullmatch(r'bytes=\d{0,20}-\d{0,20}',self.headers['Range']):self.json({'error':'Invalid range'},416);return
    headers['Range']=self.headers['Range']
   connection.request('GET',target,headers=headers);response=connection.getresponse()
   if response.status not in (200,206):
    if response.status in (301,302) and path=='/events':
     self.send_response(302);self.send_header('Location','/label-videos');self.send_header('Content-Length','0');self.end_headers();return
    self.json({'error':'Requested observation is unavailable'},response.status if 400<=response.status<=599 else 502);return
   mime=response.getheader('Content-Type','application/octet-stream')
   if path in JSON_ROUTES:
    raw=response.read(32*1024*1024+1)
    if len(raw)>32*1024*1024:raise ValueError()
    raw=json.dumps(clean(json.loads(raw)),allow_nan=False).encode()
    self.cache_response(cache_key,raw,'application/json',30 if path in ('/api/labeled-frames','/api/label-queue','/api/model-metrics','/api/training-history') else 2)
    self.send(raw);return
   if path in PAGES:
    raw=response.read(16*1024*1024).decode('utf-8')
    insertion='<link rel="stylesheet" href="/public-readonly.css"><script src="/public-readonly.js"></script>'
    raw=raw.replace('<head>','<head>'+insertion,1) if '<head>' in raw else insertion+raw
    self.send(PATHS.sub('[private path]',raw).encode(),mime='text/html; charset=utf-8');return
   if path=='/api/live/frame':
    raw=response.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError()
    self.cache_response(cache_key,raw,mime,1)
    self.send(raw,mime=mime);return
   self.send_response(response.status);self.send_header('Content-Type',mime)
   for key in ('Content-Length','Content-Range','Accept-Ranges'):
    if response.getheader(key) is not None:self.send_header(key,response.getheader(key))
   self.end_headers()
   if self.command!='HEAD':
    while block:=response.read(65536):self.wfile.write(block)
  except (ValueError,KeyError):self.json({'error':'Invalid observation request'},400)
  except (OSError,http.client.HTTPException):
   self.close_connection=True
  finally:
   if connection:connection.close()
   if acquired:self.server.upstream_slots.release()

if __name__=='__main__':
 import plistlib,subprocess
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('/Volumes/UFO-Field'));p.add_argument('--port',type=int,default=8093);p.add_argument('--upstream',type=int,default=8091);p.add_argument('--volume-uuid',default='E4920328-C7F6-4DD1-AAAB-CCE821F8CF78');a=p.parse_args()
 info=plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist',str(a.root)]))
 if info.get('VolumeUUID','').upper()!=a.volume_uuid.upper():raise SystemExit('Expected field SSD unavailable')
 Server(('127.0.0.1',a.port),a.upstream,a.root,Path(__file__).parent).serve_forever()
