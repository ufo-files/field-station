"""Only frame-image endpoints and explicit review decisions cross the HQ boundary."""
import json,time,gzip,io,urllib.request,urllib.parse,urllib.error
IMAGE_ENDPOINTS={'/api/label-queue/image','/api/labeled-image'}
class Sync:
 def __init__(self,store,origin,max_frames=5000):
  self.store=store;self.origin=origin.rstrip('/');self.last_snapshot=0;self.max_frames=max_frames;self.retry_after={}
 def request(self,path,body=None,token=None):
  parts=urllib.parse.urlsplit(path)
  if parts.scheme or parts.netloc or not path.startswith('/api/'):raise ValueError('Invalid station path')
  headers={'Accept':'application/json' if body is not None else '*/*','Accept-Encoding':'gzip'}
  if body is not None:headers.update({'Content-Type':'application/json','X-Lab-Token':token,'Origin':self.origin})
  req=urllib.request.Request(self.origin+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
  with urllib.request.urlopen(req,timeout=20) as response:
   raw=response.read(64*1024**2+1)
   if len(raw)>64*1024**2:raise ValueError('Station response exceeds limit')
   if response.headers.get('Content-Encoding')=='gzip':
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:raw=compressed.read(64*1024**2+1)
    if len(raw)>64*1024**2:raise ValueError('Expanded station response exceeds limit')
   return raw,response.headers.get('Content-Type','')
 def cycle(self):
  items=[]
  try:
   auth=json.loads(self.request('/api/labeled-frames/token')[0])
   items=self.store.outgoing()
   if items:
    response=json.loads(self.request('/api/hq/reviews',dict(items=items),auth['token'])[0]);self.store.results(items,response['results']);items=[]
   if time.time()-self.last_snapshot>60:
    snapshot=json.loads(self.request('/api/hq/snapshot')[0])
    if snapshot.get('schema')!=1:raise ValueError('Unsupported frame snapshot')
    self.store.ingest(snapshot['items'],snapshot.get('complete',False));self.last_snapshot=time.time()
   rows=sorted(self.store.rows(),key=lambda r:(r['sync_state']=='synced',r['human_reviewed'],-r.get('created',0)))[:self.max_frames]
   missing=0;downloaded=0;budget=100;protected=set();cache_full=False
   for row in rows:
    protected.add(row['id'])
    for role,url,available in [('crop',row.get('image_url'),row['cached']),('frame',row.get('frame_url'),row['context_cached'])]:
     if available or not url or self.retry_after.get((row['id'],role),0)>time.time():continue
     if budget<=0:break
     if urllib.parse.urlsplit(url).path not in IMAGE_ENDPOINTS:continue
     budget-=1
     try:
      raw,mime=self.request(url)
      if mime.split(';')[0] not in ('image/png','image/jpeg','image/webp'):raise ValueError('Not a frame image')
      if self.store.cache(row['id'],role,raw,protected,version=row['review_revision']):downloaded+=1
      else:cache_full=True;budget=0;break
     except urllib.error.HTTPError as exc:
      if exc.code not in (400,404,410,500,503):raise
      missing+=1;self.retry_after[(row['id'],role)]=time.time()+300
     except ValueError:
      missing+=1;self.retry_after[(row['id'],role)]=time.time()+300
    if budget<=0:break
   self.store.state('sync',dict(online=True,checked_epoch=time.time(),snapshot_epoch=self.last_snapshot,downloaded=downloaded,missing_frames=missing,cache_full=cache_full))
  except Exception as exc:
   if items:self.store.results(items,[])
   self.store.state('sync',dict(online=False,checked_epoch=time.time(),snapshot_epoch=self.last_snapshot,error=str(exc)[:250]))
 def run(self,stop):
  while not stop.is_set():
   self.cycle();stop.wait(5)
