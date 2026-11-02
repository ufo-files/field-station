"""Pull private field recordings; eviction follows durable verified archival only."""
import argparse,fcntl,hashlib,json,os,plistlib,shlex,shutil,subprocess,tarfile,time
from pathlib import Path
from capacity_retention import fingerprint,save

def verify_archive(path,unit):
    expected={e['path']:e for e in unit['files']};seen=set()
    with tarfile.open(path) as t:
        for m in t:
            if m.name not in expected or m.name in seen or not (m.isfile() or m.islnk()):raise ValueError('Unexpected archive member')
            if m.islnk() and m.linkname not in expected:raise ValueError('Unsafe archive link')
            h=hashlib.sha256();size=0
            with t.extractfile(m) as f:
                for b in iter(lambda:f.read(8*1024**2),b''):h.update(b);size+=len(b)
            if size!=expected[m.name]['bytes'] or h.hexdigest()!=expected[m.name]['sha256']:raise ValueError('Archive checksum mismatch')
            seen.add(m.name)
    if seen!=set(expected):raise ValueError('Incomplete archive')

def run(cfg):
    volume=Path(cfg['archive_volume']);info=plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist',str(volume)]))
    if not volume.is_mount() or info.get('VolumeUUID')!=cfg['archive_uuid']:raise ValueError('Archive SSD unavailable')
    dest=volume/'field-archive';dest.mkdir(exist_ok=True)
    def remote(action,extra=None,output=None):
        args=[cfg['field_python'],cfg['field_script'],action]+(extra or [])
        command=shlex.join(args)
        return subprocess.run([cfg['local_python'],cfg['ssh_helper'],command],stdout=output or subprocess.PIPE,check=True,timeout=3600).stdout
    with (dest/'receiver.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        status=json.loads(remote('status'));archived=[]
        for sid in status['candidates']:
            unit=json.loads(remote('inventory',['--session',sid]));key=fingerprint(unit)
            if shutil.disk_usage(volume).free<sum(e['bytes'] for e in unit['files'])+cfg['archive_reserve_gib']*1024**3:raise OSError('Archive operating reserve reached')
            folder=dest/key;folder.mkdir(exist_ok=True);target=folder/'recording.tar'
            if not target.exists():
                with (folder/'recording.partial').open('wb') as f:
                    remote('export',['--session',sid],f);f.flush();os.fsync(f.fileno())
                verify_archive(folder/'recording.partial',unit)
                (folder/'recording.partial').replace(target)
            else:verify_archive(target,unit)
            save(folder/'manifest.json',unit)
            save(folder/'receipt.json',dict(verified=True,fingerprint=key,epoch=time.time(),session=sid))
            result=json.loads(remote('evict',['--session',sid,'--receipt',key]));archived.append(dict(session=sid,result=result))
            status=json.loads(remote('status'))
            if not status['offloading']:break
        save(dest/'status.json',dict(epoch=time.time(),field=status,archived=archived))
        print(json.dumps(dict(offloading=status['offloading'],free_bytes=status['free_bytes'],archived=len(archived))),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args();run(json.loads(Path(args.config).read_text()))
