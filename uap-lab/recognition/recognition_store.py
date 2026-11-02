"""Atomic native-frame results and exact motion/track recovery state."""
import json,sqlite3,zlib,os,time
from pathlib import Path
import numpy as np
try:
 import orjson
except ImportError:
 orjson=None

def encode(value):
 return orjson.dumps(value).decode('utf-8') if orjson is not None else json.dumps(value,separators=(',',':'),allow_nan=False)

def snapshot(value):
 return orjson.loads(orjson.dumps(value)) if orjson is not None else json.loads(encode(value))
class RecognitionStore:
 def __init__(self,path):
  self.path=Path(path);self.partition_bytes=1024**3
  self.db=sqlite3.connect(path,timeout=30);self.db.execute('PRAGMA auto_vacuum=FULL');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
  self.db.executescript('CREATE TABLE IF NOT EXISTS frames(generation TEXT,sequence INTEGER,pts REAL,epoch REAL,model TEXT,observations TEXT,PRIMARY KEY(generation,sequence)); CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT,background BLOB); CREATE INDEX IF NOT EXISTS frame_time ON frames(generation,pts);')
  self.db.execute('CREATE TABLE IF NOT EXISTS archived_ranges(generation TEXT PRIMARY KEY,last_sequence INTEGER)')
  self.db.commit()
  # Finish an interrupted publish-before-delete rollover idempotently.
  for p in sorted((self.path.parent/'partitions').glob('*.sqlite')):
   archived=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
   try:ranges=list(archived.execute('SELECT generation,max(sequence) FROM frames GROUP BY generation'))
   finally:archived.close()
   for gen,last in ranges:
    self.db.execute('DELETE FROM frames WHERE generation=? AND sequence<=?',(gen,last))
    self.db.execute('INSERT INTO archived_ranges VALUES(?,?) ON CONFLICT(generation) DO UPDATE SET last_sequence=max(last_sequence,excluded.last_sequence)',(gen,last))
  self.db.commit()
 def rotate(self):
  size=(self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0])*self.db.execute('PRAGMA page_size').fetchone()[0]
  if size<self.partition_bytes:return
  ranges=list(self.db.execute('SELECT generation,min(sequence),max(sequence),min(pts),max(pts) FROM frames GROUP BY generation'))
  if not ranges:return
  folder=self.path.parent/'partitions';folder.mkdir(exist_ok=True)
  temp=folder/(str(time.time_ns())+'.pending');dest=temp.with_suffix('.sqlite')
  archive=sqlite3.connect(temp)
  try:self.db.backup(archive);archive.execute('PRAGMA journal_mode=DELETE');archive.commit()
  finally:archive.close()
  with temp.open('rb') as f:os.fsync(f.fileno())
  temp.replace(dest)
  fd=os.open(folder,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
  for gen,first,last,start,end in ranges:
   self.db.execute('DELETE FROM frames WHERE generation=? AND sequence<=?',(gen,last))
   self.db.execute('INSERT INTO archived_ranges VALUES(?,?) ON CONFLICT(generation) DO UPDATE SET last_sequence=max(last_sequence,excluded.last_sequence)',(gen,last))
  self.db.commit()
 def load(self):
  row=self.db.execute('SELECT state,background FROM checkpoint WHERE id=1').fetchone()
  if row is None:return None,None
  state=json.loads(row[0]);shape=state.get('background_shape');raw=zlib.decompress(row[1]) if state.get('background_encoding')=='zlib' else row[1];background=np.frombuffer(raw,dtype=np.float32).reshape(shape).copy() if shape else None
  return state,background
 def add(self,generation,row,model):
  archived=self.db.execute('SELECT last_sequence FROM archived_ranges WHERE generation=?',(generation,)).fetchone()
  if archived and row['sequence']<=archived[0]:raise sqlite3.IntegrityError('Native frame already archived')
  self.db.execute('INSERT INTO frames VALUES(?,?,?,?,?,?)',(generation,row['sequence'],row['pts_seconds'],row['received_epoch'],model,encode(row['observations'])))
 def commit(self,state,background):
  state=dict(state,background_shape=list(background.shape) if background is not None else None,background_encoding='zlib')
  self.db.execute('INSERT OR REPLACE INTO checkpoint VALUES(1,?,?)',(encode(state),zlib.compress(background.tobytes() if background is not None else b'',1)));self.db.commit();self.rotate()
 def close(self):self.db.rollback();self.db.close()

class AsyncRecognitionStore:
 """Bounded ordered writer; slow fsync applies backpressure instead of dropping rows."""
 def __init__(self,path,capacity=512):
  import queue,threading
  from concurrent.futures import Future
  self.pending=queue.Queue(capacity);self.error=None;self.ready=Future();self.last_committed=None;self.commit_seconds=0.
  def work():
   import time
   store=None;future=None
   try:
    store=RecognitionStore(path);state,background=store.load();self.last_committed=snapshot(state) if state else None;self.ready.set_result((state,background))
    while True:
     command=self.pending.get();future=None
     try:
      if command[0]=='close':break
      if command[0]=='add':store.add(*command[1:])
      if command[0]=='commit':
       _,state,background,future=command;started=time.perf_counter();store.commit(state,background);self.commit_seconds+=time.perf_counter()-started;self.last_committed=state;future.set_result(state)
     finally:self.pending.task_done()
   except BaseException as exc:
    self.error=exc
    if not self.ready.done():self.ready.set_exception(exc)
    if future and not future.done():future.set_exception(exc)
   finally:
    if store:store.close()
  self.thread=threading.Thread(target=work,daemon=True);self.thread.start()
 def _put(self,command):
  import queue
  while True:
   if self.error:raise RuntimeError('Recognition writer failed: '+str(self.error)) from self.error
   try:self.pending.put(command,timeout=.1);return
   except queue.Full:continue
 def load(self):return self.ready.result()
 def add(self,generation,row,model):self._put(('add',generation,row,model))
 def commit(self,state,background):
  from concurrent.futures import Future
  future=Future();saved=snapshot(state);self._put(('commit',saved,background.copy() if background is not None else None,future));return future
 def close(self):
  if not self.error:self._put(('close',))
  self.thread.join()
  if self.error:raise RuntimeError('Recognition writer failed: '+str(self.error)) from self.error
