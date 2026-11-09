"""Authenticated read-only recovery of verified archives over the private mesh."""
import argparse,hashlib,hmac,json,os,plistlib,re,subprocess,tarfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path,PurePosixPath
from urllib.parse import unquote,urlsplit

def package(root,key):
 if not re.fullmatch('[a-f0-9]{64}',key):raise ValueError('Invalid archive identity')
 folder=Path(root)/key
 if folder.is_symlink():raise ValueError('Unsafe archive')
 unit=json.loads((folder/'manifest.json').read_text());receipt=json.loads((folder/'receipt.json').read_text());copy=json.loads((folder/'.replica-receipt.json').read_text())
 identity=hashlib.sha256(json.dumps(unit,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 if identity!=key or not receipt.get('verified') or receipt.get('fingerprint')!=key or not copy.get('verified_at'):raise ValueError('Archive not verified')
 return folder,unit

def member(root,key,name):
 p=PurePosixPath(name)
 if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe member')
 folder,unit=package(root,key)
 entry=next((e for e in unit['files'] if e['path']==name),None)
 if not entry:raise FileNotFoundError(name)
 archive=folder/'recording.tar'
 if archive.is_symlink():raise ValueError('Unsafe archive')
 bundle=tarfile.open(archive,'r:');item=bundle.getmember(name)
 if not item.isfile() or item.size!=entry['bytes']:bundle.close();raise ValueError('Invalid archived member')
 return bundle,bundle.extractfile(item),entry

def handler(cfg):
 volume=Path(cfg['volume']);device=volume.stat().st_dev
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+cfg['token']):self.send_error(403);return
   if not volume.is_mount() or volume.stat().st_dev!=device:self.send_error(503);return
   path=unquote(urlsplit(self.path).path);parts=path.split('/',3)
   if len(parts)!=4 or parts[1]!='v1':self.send_error(404);return
   key,name=parts[2:]
   bundle=None;inp=None
   try:
    if name=='manifest.json':
     _,unit=package(cfg['root'],key);body=json.dumps(unit).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
    bundle,inp,entry=member(cfg['root'],key,name)
    self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(entry['bytes']));self.send_header('X-Content-SHA256',entry['sha256']);self.end_headers()
    for block in iter(lambda:inp.read(1024**2),b''):self.wfile.write(block)
   except (ValueError,OSError,KeyError,tarfile.TarError):
    if bundle is None:self.send_error(404)
   finally:
    if inp:inp.close()
    if bundle:bundle.close()
  def log_message(self,*args):pass
 return Handler

def main(cfg):
 info=plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist',cfg['volume']]))
 if info.get('VolumeUUID')!=cfg['uuid'] or not Path(cfg['volume']).is_mount():raise ValueError('Archive volume unavailable')
 ThreadingHTTPServer((cfg['host'],cfg['port']),handler(cfg)).serve_forever()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();main(json.loads(Path(a.config).read_text()))
