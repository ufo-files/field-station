"""Durable, observed CE5 playback intervals; never infer activity from a toggle."""
import sqlite3
from contextlib import contextmanager,closing
from pathlib import Path

@contextmanager
def connect(root):
 path=Path(root)/'audio/playback.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(path,timeout=5)
 try:
  with db:
   db.execute('CREATE TABLE IF NOT EXISTS playback (id INTEGER PRIMARY KEY, track TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL)')
   yield db
 finally:db.close()

def begin(root,track,now):
 with connect(root) as db:
  return db.execute('INSERT INTO playback(track,start,end) VALUES (?,?,?)',(Path(track).name,now,now)).lastrowid

def observed(root,identity,now):
 with connect(root) as db:db.execute('UPDATE playback SET end=max(end,?) WHERE id=?',(now,identity))

def overlap(root,manifest):
 start=manifest.get('started_epoch');end=manifest.get('clip_end_epoch') or manifest.get('stopped_epoch')
 if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or end<=start:return []
 path=Path(root)/'audio/playback.sqlite3'
 if not path.is_file():return []
 # Read-only access must not create storage or turn an absent history into evidence.
 with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
  return [dict(track=row[0],started_epoch=row[1],observed_until_epoch=row[2]) for row in db.execute('SELECT track,start,end FROM playback WHERE start < ? AND end > ? AND end > start ORDER BY start',(end,start))]
