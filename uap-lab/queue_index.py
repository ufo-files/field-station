"""Small chronological index; authoritative events and receipts stay on disk."""
import os,re,sqlite3,time
from pathlib import Path

def connect(root):
 db=sqlite3.connect(Path(root)/'review-queue.sqlite',timeout=30)
 db.execute('PRAGMA journal_mode=WAL')
 db.execute('CREATE TABLE IF NOT EXISTS entries (id TEXT PRIMARY KEY, stamp INTEGER NOT NULL)')
 db.execute('CREATE INDEX IF NOT EXISTS entries_time ON entries(stamp DESC,id DESC)')
 return db

def touch(root,key):
 if not re.fullmatch('[a-f0-9]{32}',key):return
 with connect(root) as db:db.execute('INSERT INTO entries VALUES (?,?) ON CONFLICT(id) DO UPDATE SET stamp=excluded.stamp',(key,time.time_ns()))
 db.close()

def ordered(root,boundary=None):
 root=Path(root)
 if not root.exists():return []
 with connect(root) as db:
  known={r[0] for r in db.execute('SELECT id FROM entries')};new=[]
  with os.scandir(root) as stream:
   for e in stream:
    if e.name not in known and re.fullmatch('[a-f0-9]{32}',e.name):
     try:new.append((e.name,e.stat().st_mtime_ns))
     except FileNotFoundError:continue
  db.executemany('INSERT OR IGNORE INTO entries VALUES (?,?)',new)
  if boundary:rows=list(db.execute('SELECT stamp,id FROM entries WHERE (stamp,id)<(?,?) ORDER BY stamp DESC,id DESC',boundary))
  else:rows=list(db.execute('SELECT stamp,id FROM entries ORDER BY stamp DESC,id DESC'))
 db.close();return rows
