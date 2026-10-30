"""Immutable, checksum-verified field archives on the dedicated M6 data volume."""
import hashlib,json,os,re,shutil,sys,time
from pathlib import Path,PurePosixPath
VOLUME=Path('/Volumes/UFO Files Archive 4')
ROOT=VOLUME/'ufo-field-m1'
RESERVE=200*1024**3

def canonical(index):return json.dumps(index,sort_keys=True,separators=(',',':')).encode()
def validate(index):
    if index.get('schema')!=1 or not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',index.get('session_id','')):raise ValueError('Invalid archive identity')
    files=index.get('files',[])
    if not files or len(files)>20000:raise ValueError('Invalid archive inventory')
    names=set()
    for entry in files:
        name=entry['name'];p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or str(p)!=name or name in names or name=='transfer-index.json':raise ValueError('Unsafe or duplicate archive path')
        if not isinstance(entry['bytes'],int) or entry['bytes']<0 or not re.fullmatch('[a-f0-9]{64}',entry['sha256']):raise ValueError('Invalid archive checksum')
        names.add(name)
    return hashlib.sha256(canonical(index)).hexdigest()
def paths(root,index):
    fingerprint=validate(index);sid=index['session_id']
    return root/'incoming'/(sid+'-'+fingerprint),root/'sessions'/sid/fingerprint,fingerprint

def prepare(root,index,reserve=RESERVE):
    incoming,final,fingerprint=paths(root,index)
    if final.exists():return dict(state='verified',fingerprint=fingerprint,receipt=json.loads((final/'receipt.json').read_text()))
    needed=sum(e['bytes'] for e in index['files'])
    if shutil.disk_usage(root).free-needed<reserve:raise ValueError('M6 archive reserve would be exceeded')
    incoming.mkdir(parents=True,exist_ok=True)
    target=incoming/'transfer-index.json';raw=canonical(index)
    if target.exists() and target.read_bytes()!=raw:raise ValueError('Archive inventory changed')
    target.write_bytes(raw)
    return dict(state='ready',fingerprint=fingerprint,destination='ufo-processing/field-archive/incoming/'+incoming.name+'/')

def verify(root,index):
    incoming,final,fingerprint=paths(root,index)
    if final.exists():return json.loads((final/'receipt.json').read_text())
    for entry in index['files']:
        path=incoming/entry['name']
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(incoming.resolve()):raise ValueError('Unsafe or missing archived file')
        if path.stat().st_size!=entry['bytes']:raise ValueError('Archived file size mismatch')
        digest=hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
            os.fsync(f.fileno())
        if digest.hexdigest()!=entry['sha256']:raise ValueError('Archived SHA256 mismatch')
    receipt=dict(schema=1,session_id=index['session_id'],fingerprint=fingerprint,verified_epoch=time.time(),files=index['files'],destination=str(final))
    with (incoming/'receipt.json').open('w') as f:json.dump(receipt,f);f.flush();os.fsync(f.fileno())
    final.parent.mkdir(parents=True,exist_ok=True);incoming.rename(final)
    return receipt

def main():
    if not VOLUME.is_mount() or not ROOT.is_dir() or ROOT.stat().st_dev!=VOLUME.stat().st_dev:raise ValueError('Dedicated archive volume unavailable')
    index=json.load(sys.stdin);command=sys.argv[1]
    if command=='prepare':result=prepare(ROOT,index)
    elif command=='verify':result=verify(ROOT,index)
    else:raise ValueError('Invalid archive operation')
    print(json.dumps(result))
if __name__=='__main__':main()
