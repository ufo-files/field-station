"""Persistent HTTP entry point while the lab is restarted for maintenance."""
import argparse,http.client,json,os,socket,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOP={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade'}

def maintenance(path):
 try:
  record=json.loads(path.read_text())
  if time.time()-record['started_epoch']>1800:return None
  os.kill(record['pid'],0)
  return record
 except (OSError,ValueError,KeyError,TypeError):return None

class Frontend(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def send(self,data,status=200,mime='application/json'):
  self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers()
  if self.command!='HEAD':self.wfile.write(data)
 def state(self):
  record=maintenance(self.server.marker)
  if record:return dict(available=False,phase='cleanup',title='Cleanup in progress',message='The station is clearing its backlog. Your saved labels and training data are retained. This page will return automatically.')
  connection=http.client.HTTPConnection('127.0.0.1',self.server.upstream,timeout=2)
  try:
   connection.request('GET','/api/service-health');response=connection.getresponse();value=json.loads(response.read())
   if response.status==200 and value.get('ready'):return dict(available=True,phase='ready',instance=value['instance'])
  except (OSError,http.client.HTTPException,ValueError,KeyError):pass
  finally:connection.close()
  return dict(available=False,phase='reconnecting',title='Reconnecting to Field Station',message='The web service is restarting or temporarily unavailable. This page will return automatically when it is ready.')
 def unavailable(self,state):
  if self.command in ('GET','HEAD') and not urlsplit(self.path).path.startswith('/api/') and ('.' not in urlsplit(self.path).path):
   self.send((self.server.static/'maintenance.html').read_bytes(),200,'text/html; charset=utf-8')
  else:self.send(json.dumps(dict(error=state['title'],maintenance=True)).encode(),503)
 def forward(self):
  path=urlsplit(self.path).path
  if path=='/api/service-status':self.send(json.dumps(self.state()).encode());return
  if path in ('/maintenance.js','/app-shell.css'):
   file=self.server.static/path[1:];self.send(file.read_bytes(),200,'text/javascript' if file.suffix=='.js' else 'text/css');return
  if maintenance(self.server.marker):
   # Do not consume or retry a mutation during maintenance.
   self.close_connection=True;self.unavailable(self.state());return
  connection=http.client.HTTPConnection('127.0.0.1',self.server.upstream,timeout=120)
  started=False
  try:
   if self.headers.get('Transfer-Encoding'):self.send(b'{"error":"Content-Length required"}',411);return
   connection.putrequest(self.command,self.path,skip_host=True,skip_accept_encoding=True)
   for key,value in self.headers.items():
    if key.lower() not in HOP:connection.putheader(key,value)
   connection.putheader('Connection','close');connection.endheaders()
   remaining=int(self.headers.get('Content-Length',0))
   while remaining:
    chunk=self.rfile.read(min(1024*1024,remaining))
    if not chunk:raise ConnectionError('Interrupted upload')
    connection.send(chunk);remaining-=len(chunk)
   response=connection.getresponse();self.send_response(response.status)
   for key,value in response.getheaders():
    if key.lower() not in HOP:self.send_header(key,value)
   self.send_header('Connection','close');self.end_headers();started=True;self.close_connection=True
   if self.command!='HEAD':
    while True:
     chunk=response.read(256*1024)
     if not chunk:break
     self.wfile.write(chunk)
  except (OSError,http.client.HTTPException,ValueError):
   self.close_connection=True
   if not started:self.unavailable(self.state())
  finally:connection.close()
 def do_GET(self):self.forward()
 def do_HEAD(self):self.forward()
 def do_POST(self):self.forward()
 def log_message(self,*args):pass

def server(port,upstream,marker,static):
 result=ThreadingHTTPServer(('127.0.0.1',port),Frontend);result.daemon_threads=True;result.upstream=upstream;result.marker=Path(marker);result.static=Path(static);return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8091);p.add_argument('--upstream',type=int,default=8092);p.add_argument('--marker',type=Path,default=Path(__file__).resolve().parent.parent/'run/web-maintenance.json');a=p.parse_args()
 server(a.port,a.upstream,a.marker,Path(__file__).parent/'static').serve_forever()
