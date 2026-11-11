"""External-drive review cache with durable, per-object outgoing decisions."""
import hashlib,json,os,sqlite3,time,uuid
from pathlib import Path
from contextlib import contextmanager

class Store:
 def __init__(self,root,limit=20*1024**3):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.limit=limit
  (self.root/'frames').mkdir(exist_ok=True)
  with self.db() as db:
   db.executescript("""PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;
   CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY,row TEXT NOT NULL,seen REAL NOT NULL);
   CREATE TABLE IF NOT EXISTS media(object_id TEXT,role TEXT,path TEXT,bytes INTEGER,access REAL,PRIMARY KEY(object_id,role));
   CREATE TABLE IF NOT EXISTS decisions(request_id TEXT PRIMARY KEY,object_id TEXT,label TEXT,base_revision TEXT,reviewer TEXT,state TEXT,created REAL,result TEXT);
   CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
   CREATE INDEX IF NOT EXISTS decision_object ON decisions(object_id,state);
   """)
   if 'version' not in {c[1] for c in db.execute('PRAGMA table_info(media)')}:db.execute('ALTER TABLE media ADD COLUMN version TEXT')
   db.execute("UPDATE decisions SET state='pending' WHERE state='sending'")
   referenced={row[0] for row in db.execute('SELECT path FROM media')}
   for path in (self.root/'frames').iterdir():
    if str(path.relative_to(self.root)) not in referenced:path.unlink()
   for row in db.execute('SELECT object_id,role,path FROM media').fetchall():
    if not (self.root/row['path']).is_file():db.execute('DELETE FROM media WHERE object_id=? AND role=?',(row['object_id'],row['role']))
 @contextmanager
 def db(self):
  db=sqlite3.connect(self.root/'reviews.sqlite',timeout=30);db.row_factory=sqlite3.Row
  try:
   with db:yield db
  finally:db.close()
 def state(self,key,value=None):
  with self.db() as db:
   if value is not None:db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',(key,json.dumps(value)));return value
   row=db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone();return json.loads(row[0]) if row else None
 def ingest(self,rows,complete=True):
  stamp=time.time()
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   for row in rows:db.execute('INSERT OR REPLACE INTO objects VALUES(?,?,?)',(row['id'],json.dumps(row),stamp))
   if complete:
    stale=db.execute("SELECT id FROM objects WHERE seen<? AND id NOT IN (SELECT object_id FROM decisions WHERE state!='synced')",(stamp,)).fetchall()
    for row in stale:
     self.drop_media(db,row['id']);db.execute('DELETE FROM objects WHERE id=?',(row['id'],))
 def drop_media(self,db,key):
  for row in db.execute('SELECT path FROM media WHERE object_id=?',(key,)).fetchall():(self.root/row[0]).unlink(missing_ok=True)
  db.execute('DELETE FROM media WHERE object_id=?',(key,))
 def cache(self,key,role,raw,protected=(),version=None):
  if role not in ('crop','frame') or not raw or len(raw)>16*1024**2:raise ValueError('Invalid frame size')
  name='frames/'+hashlib.sha256((key+':'+role).encode()).hexdigest()
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   old=db.execute('SELECT bytes FROM media WHERE object_id=? AND role=?',(key,role)).fetchone();used=db.execute('SELECT COALESCE(SUM(bytes),0) FROM media').fetchone()[0]
   while used+len(raw)-(old[0] if old else 0)>self.limit:
    candidates=db.execute("SELECT object_id FROM media WHERE object_id!=? AND object_id NOT IN (SELECT object_id FROM decisions WHERE state!='synced') GROUP BY object_id ORDER BY MIN(access)",(key,)).fetchall()
    victim=next((candidate for candidate in candidates if candidate[0] not in protected),None)
    if not victim:return False
    self.drop_media(db,victim[0]);used=db.execute('SELECT COALESCE(SUM(bytes),0) FROM media').fetchone()[0]
   temp=self.root/(name+'.tmp')
   with temp.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
   temp.replace(self.root/name)
   db.execute('INSERT OR REPLACE INTO media VALUES(?,?,?,?,?,?)',(key,role,name,len(raw),time.time(),version))
  return True
 def rows(self):
  with self.db() as db:
   media={}
   for m in db.execute('SELECT object_id,role,version FROM media'):media.setdefault(m[0],{})[m[1]]=m[2]
   pending={r['object_id']:dict(r) for r in db.execute("SELECT * FROM decisions WHERE state!='synced' ORDER BY created")}
   rows=[]
   for entry in db.execute('SELECT row FROM objects'):
    row=json.loads(entry[0]);key=row['id'];available=media.get(key,{})
    def cached(role):return role in available and (key in pending or available[role] in (None,row['review_revision']))
    row['cached']=cached('crop');row['context_cached']=cached('frame')
    if key in pending:
     op=pending[key];row.update(label=op['label'],human_reviewed=True,sync_state=op['state'],request_id=op['request_id'],sync_result=json.loads(op['result'] or '{}'))
    else:row['sync_state']='synced'
    rows.append(row)
   return sorted(rows,key=lambda r:(r.get('created',0),r['id']),reverse=True)
 def queue(self,ids,label,reviewer,revisions=None,replaces=None):
  if label not in ('anomalous','not_anomalous') or not isinstance(ids,list) or not 1<=len(ids)<=500:raise ValueError('Choose 1–500 frames')
  results=[]
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   for key in dict.fromkeys(ids):
    entry=db.execute('SELECT row FROM objects WHERE id=?',(key,)).fetchone()
    if not entry or not db.execute("SELECT 1 FROM media WHERE object_id=? AND role='crop'",(key,)).fetchone():raise ValueError('Frame is not available offline yet')
    old=db.execute("SELECT * FROM decisions WHERE object_id=? AND state!='synced' ORDER BY created DESC LIMIT 1",(key,)).fetchone()
    if old and old['state'] in ('sending','conflict','attention'):raise ValueError('Resolve this frame’s pending sync before changing it')
    row=json.loads(entry[0])
    if revisions is not None and revisions.get(key)!=row['review_revision']:raise ValueError('This frame changed. Refresh before reviewing it.')
    if old and old['label']==label:results.append(old['request_id']);continue
    if old and (replaces or {}).get(key)!=old['request_id']:raise ValueError('Another HQ review is pending. Refresh to see that decision before changing it.')
    request=uuid.uuid4().hex
    if old:db.execute('DELETE FROM decisions WHERE request_id=?',(old['request_id'],))
    db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?)',(request,key,label,row['review_revision'],reviewer[:100],'pending',time.time(),None));results.append(request)
  return results
 def outgoing(self):
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');rows=[dict(r) for r in db.execute("SELECT * FROM decisions WHERE state='pending' ORDER BY created LIMIT 50")]
   for row in rows:db.execute("UPDATE decisions SET state='sending' WHERE request_id=?",(row['request_id'],))
  return [dict(id=r['object_id'],label=r['label'],base_revision=r['base_revision'],request_id=r['request_id'],reviewer=r['reviewer']) for r in rows]
 def results(self,items,results):
  received={r['request_id']:r for r in results}
  with self.db() as db:
   for item in items:
    result=received.get(item['request_id']);state=result.get('state','attention') if result else 'pending'
    if state not in ('synced','pending','conflict','attention'):state='attention'
    db.execute('UPDATE decisions SET state=?,result=? WHERE request_id=?',(state,json.dumps(result) if result else None,item['request_id']))
    if state=='synced':
     found=db.execute('SELECT row FROM objects WHERE id=?',(item['id'],)).fetchone()
     if found:
      row=json.loads(found[0]);row.update(label=item['label'],human_reviewed=True,review_revision=result['review_revision']);db.execute('UPDATE media SET version=? WHERE object_id=?',(result['review_revision'],item['id']));db.execute('UPDATE objects SET row=? WHERE id=?',(json.dumps(row),item['id']))
 def resolve(self,request,action):
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');op=db.execute('SELECT * FROM decisions WHERE request_id=?',(request,)).fetchone()
   if not op or op['state'] not in ('conflict','attention'):raise ValueError('No review conflict to resolve')
   if action=='field':
    result=json.loads(op['result'] or '{}');entry=db.execute('SELECT row FROM objects WHERE id=?',(op['object_id'],)).fetchone()
    if entry and result.get('current_revision'):
     row=json.loads(entry[0]);row.update(review_revision=result['current_revision'],label=result.get('current_label') or row['label'],human_reviewed=result['current_revision']!='unreviewed');db.execute('UPDATE objects SET row=? WHERE id=?',(json.dumps(row),op['object_id']))
    db.execute('DELETE FROM decisions WHERE request_id=?',(request,));return
   result=json.loads(op['result'] or '{}')
   if action!='retry' or not result.get('current_revision'):raise ValueError('Refresh this object before retrying')
   db.execute("UPDATE decisions SET request_id=?,base_revision=?,state='pending',result=NULL WHERE request_id=?",(uuid.uuid4().hex,result['current_revision'],request))
 def image(self,key,role):
  with self.db() as db:
   row=db.execute('SELECT path FROM media WHERE object_id=? AND role=?',(key,role)).fetchone()
   if not row:raise FileNotFoundError('Frame not cached')
   db.execute('UPDATE media SET access=? WHERE object_id=?',(time.time(),key));return self.root/row[0]
 def summary(self):
  with self.db() as db:
   states={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM decisions GROUP BY state')};used=db.execute('SELECT COALESCE(SUM(bytes),0) FROM media').fetchone()[0];count=db.execute("SELECT COUNT(*) FROM media WHERE role='crop'").fetchone()[0]
  return dict(sync=self.state('sync') or {},decisions=states,cache_bytes=used,cache_limit_bytes=self.limit,cached_frames=count)
