"""HQ review role: local frame cache and queued labels, with no capture or video storage."""
import argparse,json,mimetypes,os,secrets,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from store import Store
from sync import Sync
TOKEN=secrets.token_urlsafe(32)
class Server(ThreadingHTTPServer):
 daemon_threads=True;request_queue_size=128
class Handler(BaseHTTPRequestHandler):
 def send(self,value,status=200,mime='application/json'):
  raw=value if isinstance(value,bytes) else json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  try:
   p=urlsplit(self.path);q=parse_qs(p.query);store=self.server.store
   if p.path=='/api/status':self.send(dict(store.summary(),token=TOKEN));return
   if p.path=='/api/models':
    def read_file(path,default):
     try:return json.loads(path.read_text())
     except (FileNotFoundError,ValueError):return default
    root=getattr(self.server,'hybrid',None);backup=getattr(self.server,'backup',None)
    state=read_file(root/'status.json',{}) if root else {}
    allowed=('phase','human_version','shadow_version','shadow_seed_only','pseudo_labels','comparison_objects','human_examples','updated_epoch','trained_epoch','reason','error')
    self.send(dict(experiment={k:state[k] for k in allowed if k in state},metrics=read_file(root/'metrics.json',{}) if root else {},backup=read_file(backup/'current/backup-receipt.json',{}) if backup else {}));return

   if p.path=='/api/objects':
    review=q.get('review',['needs_review'])[0];label=q.get('label',['all'])[0];offset=max(0,int(q.get('offset',['0'])[0]));rows=[r for r in store.rows() if r['cached']]
    def matches(r,v):return v=='all' or (v=='needs_review' and not r['human_reviewed']) or (v=='human_reviewed' and r['human_reviewed']) or (v=='attention' and r['sync_state'] in ('conflict','attention'))
    counts=dict(review={v:sum(matches(r,v) and (label=='all' or r['label']==label) for r in rows) for v in ('all','needs_review','human_reviewed','attention')},classification={v:sum(matches(r,review) and (v=='all' or r['label']==v) for r in rows) for v in ('all','anomalous','not_anomalous')})
    rows=[r for r in rows if (review=='all' or (review=='needs_review' and not r['human_reviewed']) or (review=='human_reviewed' and r['human_reviewed']) or (review=='attention' and r['sync_state'] in ('conflict','attention'))) and (label=='all' or r['label']==label)]
    self.send(dict(items=rows[offset:offset+100],total=len(rows),counts=counts));return
   if p.path=='/api/image':
    path=store.image(q['id'][0],q.get('role',['crop'])[0]);raw=path.read_bytes();mime='image/png' if raw.startswith(b'\x89PNG') else 'image/webp' if raw[8:12]==b'WEBP' else 'image/jpeg';self.send(raw,mime=mime);return
   if p.path.startswith('/fonts/'):
    name=p.path.removeprefix('/fonts/')
    if name not in ('IBMPlexMono-Regular.woff2',):raise FileNotFoundError()
    self.send((self.server.fonts/name).read_bytes(),mime='font/woff2');return
   files={'/':'index.html','/label-videos':'index.html','/app.js':'app.js','/style.css':'style.css','/models':'models.html','/models.js':'models.js'}
   if p.path not in files:raise FileNotFoundError()
   path=self.server.static/files[p.path];self.send(path.read_bytes(),mime=mimetypes.guess_type(path.name)[0] or 'text/plain')
  except (FileNotFoundError,KeyError):self.send(dict(error='Frame not available in the HQ cache'),404)
  except (ValueError,OSError) as exc:self.send(dict(error=str(exc)),400)
 def do_POST(self):
  try:
   origin=self.headers.get('Origin');length=int(self.headers.get('Content-Length','0'))
   if self.headers.get('X-HQ-Token')!=TOKEN or (origin and urlsplit(origin).netloc!=self.headers.get('Host')):self.send(dict(error='Reload to reconnect securely'),403);return
   if not 0<length<1024*1024:raise ValueError('Invalid request size')
   body=json.loads(self.rfile.read(length));path=urlsplit(self.path).path
   if path=='/api/review':self.send(dict(saved=True,requests=self.server.store.queue(body.get('ids'),body.get('label'),str(body.get('reviewer','HQ reviewer')),body.get('revisions',{}),body.get('replaces',{}))));return
   if path=='/api/resolve':self.server.store.resolve(body.get('request_id'),body.get('action'));self.send(dict(saved=True));return
   self.send(dict(error='Review operation not found'),404)
  except (ValueError,KeyError,TypeError) as exc:self.send(dict(error=str(exc)),400)
 def log_message(self,*args):pass

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();cfg=json.loads(Path(a.config).read_text());volume=Path(cfg['volume'])
 if not volume.is_mount() or (volume/'.hq-review-volume').read_text().strip()!=cfg['volume_id']:raise RuntimeError('HQ external storage is unavailable')
 root=Path(cfg['data'])
 if not root.resolve().is_relative_to(volume.resolve()):raise ValueError('HQ data must stay on its external drive')
 store=Store(root,int(cfg.get('cache_gib',20))*1024**3);server=Server((cfg.get('bind','127.0.0.1'),cfg.get('port',8091)),Handler);server.store=store;server.static=Path(__file__).parent/'static';server.fonts=Path(__file__).parent.parent/'uap-lab/static/fonts'
 server.hybrid=Path(cfg['hybrid_data']) if cfg.get('hybrid_data') else None;server.backup=Path(cfg['training_backup']) if cfg.get('training_backup') else None
 for target in (server.hybrid,server.backup):
  if target is not None and not target.resolve().is_relative_to(volume.resolve()):raise ValueError('Model and backup data must stay on external storage')
 stop=threading.Event();worker=threading.Thread(target=Sync(store,cfg['field_origin'],cfg.get('max_cached_frames',5000)).run,args=(stop,),daemon=True);worker.start()
 try:server.serve_forever()
 finally:stop.set();server.server_close()
if __name__=='__main__':main()
