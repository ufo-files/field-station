"""Read ordered native results across immutable partitions and the live database."""
import heapq,itertools,sqlite3
from pathlib import Path

class History:
    def __init__(self,path):self.path=Path(path);self.connections=[]
    def close(self):
        for db in self.connections:db.close()
        self.connections=[]
    def execute(self,sql,params=()):
        self.close();cursors=[]
        # Open the live DB first and establish its read snapshot BEFORE enumerating
        # partitions. During rollover, this sees either original rows or the shard.
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=5)
        def collect(db):
            cursor=db.execute(sql,params);first=cursor.fetchone()
            if first is None:db.close();return
            if 'SELECT pts ' in sql:
                cursors.append(iter([first]));db.close();return
            self.connections.append(db);cursors.append(itertools.chain([first],cursor))
        collect(db)
        for p in sorted((self.path.parent/'partitions').glob('*.sqlite')):
            if p.is_symlink():raise ValueError('Unsafe recognition partition')
            db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5);collect(db)
        if 'SELECT pts ' in sql:
            values=[r[0] for c in cursors if (r:=next(c,None)) is not None]
            return Rows(iter([] if not values else [(max(values) if 'DESC' in sql else min(values),)]))
        def merged():
            previous=None
            for row in heapq.merge(*cursors,key=lambda r:r[0]):
                if row[0]!=previous:yield row;previous=row[0]
        return Rows(merged())
class Rows:
    def __init__(self,rows):self.rows=iter(rows)
    def __iter__(self):return self.rows
    def fetchone(self):return next(self.rows,None)
