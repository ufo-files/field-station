"""Indexed recording lookup; manifests remain authoritative for archive decisions."""
import concurrent.futures,json,os,re,sqlite3
from pathlib import Path
SID=re.compile(r'[0-9TZ]+-[a-f0-9]{6}')

def configured():
 value=os.environ.get('CAPTURE_SESSION_INDEX')
 return Path(value) if value else None

def connect(path):
 if str(path).startswith('/Volumes/') and not Path(*path.parts[:3]).is_mount():raise OSError('Session index SSD is unavailable')
 path.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(path,timeout=2)
 db.execute('PRAGMA journal_mode=WAL')
 db.execute('CREATE TABLE IF NOT EXISTS sessions(root TEXT, id TEXT, generation TEXT, PRIMARY KEY(root,id))')
 db.execute('CREATE INDEX IF NOT EXISTS sessions_generation ON sessions(root,generation)')
 db.execute('CREATE TABLE IF NOT EXISTS session_windows(root TEXT,id TEXT,start REAL,end REAL,PRIMARY KEY(root,id))')
 db.execute('CREATE TABLE IF NOT EXISTS catalog(root TEXT PRIMARY KEY, ready INTEGER NOT NULL)')
 return db

def register_manifest(path,value):
 """Called before publishing a recording manifest, including its first write."""
 path=Path(path);index=configured()
 if not index or path.name!='manifest.json' or path.parent.parent.name!='sessions' or not SID.fullmatch(path.parent.name):return
 generation=value.get('spool_generation')
 if not generation:return
 root=path.parent.parent.parent
 try:
  with connect(index) as db:
   db.execute('INSERT INTO sessions VALUES (?,?,?) ON CONFLICT(root,id) DO UPDATE SET generation=excluded.generation WHERE generation!=excluded.generation',(str(root),path.parent.name,generation))
   db.execute('DELETE FROM session_windows WHERE root=? AND id=?',(str(root),path.parent.name))
   register_window(db,root,path.parent,value)
  db.close()
 except (OSError,sqlite3.Error):
  # A failed index write must force the reader back to authoritative discovery.
  (root/'session-catalog-invalid').write_text('Recording metadata changed while the index was unavailable')

def window_value(root,folder,manifest=None):
 """Only closed recording windows are stable; active recordings remain candidates."""
 try:
  value=manifest if manifest is not None else json.loads((folder/'manifest.json').read_text())
  if value.get('state') not in ('completed','interrupted'):return
  segments=json.loads((folder/'buffer-state.json').read_text()).get('segments',[])
  if not segments:return
  start=float(segments[0]['start']);end=float(segments[-1]['end'])
  if not start<end:return
  return (str(root),folder.name,start,end)
 except (OSError,ValueError,KeyError,TypeError):return

def register_window(db,root,folder,manifest=None):
 value=window_value(root,folder,manifest)
 if value:db.execute('INSERT OR REPLACE INTO session_windows VALUES (?,?,?,?)',value)

def invalidate_window(path):
 """Called before a buffer update, so changed ranges are never filtered out."""
 path=Path(path);index=configured()
 if not index or path.name!='buffer-state.json' or path.parent.parent.name!='sessions':return
 root=path.parent.parent.parent
 try:
  with connect(index) as db:db.execute('INSERT OR REPLACE INTO session_windows VALUES (?,?,NULL,NULL)',(str(root),path.parent.name))
  db.close()
 except (OSError,sqlite3.Error):(root/'session-catalog-invalid').write_text('Recording window changed while index was unavailable')

def lookup(root,generation,pts=None):
 index=configured();root=Path(root)
 if not index:return None
 try:
  if (root/'session-catalog-invalid').exists() or not index.is_file():return None
  with connect(index) as db:
   ready=db.execute('SELECT ready FROM catalog WHERE root=?',(str(root),)).fetchone()
   result=None
   if ready and ready[0]:
    if pts is not None:
     # Backfill old catalog entries once; subsequent saves use the time index.
     missing=list(db.execute('SELECT s.id FROM sessions s LEFT JOIN session_windows w ON s.root=w.root AND s.id=w.id WHERE s.root=? AND s.generation=? AND w.id IS NULL',(str(root),generation)))
     windows=[v for (sid,) in missing if (v:=window_value(root,root/'sessions'/sid)) is not None]
     db.executemany('INSERT OR IGNORE INTO session_windows VALUES (?,?,?,?)',windows)
     result=[root/'sessions'/r[0] for r in db.execute('SELECT s.id FROM sessions s LEFT JOIN session_windows w ON s.root=w.root AND s.id=w.id WHERE s.root=? AND s.generation=? AND (w.start IS NULL OR (w.start<=? AND w.end>?))',(str(root),generation,pts,pts))]
    else:result=[root/'sessions'/r[0] for r in db.execute('SELECT id FROM sessions WHERE root=? AND generation=?',(str(root),generation))]
  db.close();return result
 except (OSError,sqlite3.Error):return None

def rebuild(root):
 """One migration scan. New manifests are maintained incrementally by the writer."""
 root=Path(root);index=configured()
 if not index:raise ValueError('CAPTURE_SESSION_INDEX is not configured')
 def load(folder):
  try:
   value=json.loads((folder/'manifest.json').read_text());generation=value.get('spool_generation')
   return (str(root),folder.name,generation) if generation else None
  except FileNotFoundError:return None
 folders=[root/'sessions'/name for name in os.listdir(root/'sessions') if SID.fullmatch(name)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=[r for r in pool.map(load,folders) if r]
 with connect(index) as db:
  db.executemany('INSERT INTO sessions VALUES (?,?,?) ON CONFLICT(root,id) DO UPDATE SET generation=excluded.generation',rows)
  db.execute('DELETE FROM session_windows WHERE root=?',(str(root),))
  db.execute('INSERT INTO catalog VALUES (?,1) ON CONFLICT(root) DO UPDATE SET ready=1',(str(root),))
 db.close();(root/'session-catalog-invalid').unlink(missing_ok=True)
 return dict(recordings=len(rows),index=str(index))
