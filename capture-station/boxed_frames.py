#!/usr/bin/env python3
"""Keep independent boxed-image copies in sessions/boxed-frames for quick review."""
import argparse
import json
from classification_labels import effective_classification
import os
from pathlib import Path
import re
import signal
import stat
import tempfile
import threading

SID=re.compile(r'[0-9TZ]+-[a-f0-9]{6}')
BOXED=re.compile(r'motion-[a-f0-9]{16}-boxed\.jpg')


def signature(metadata):
    return metadata.st_dev,metadata.st_ino,metadata.st_size,metadata.st_mtime_ns


def copy_boxed(source,destination):
    """Atomically copy a complete annotation, retrying if its source is replaced."""
    if source.is_symlink() or destination.is_symlink():raise ValueError('Boxed-frame paths must not be symlinks')
    metadata=source.stat()
    if destination.is_file():
        existing=destination.stat()
        if (existing.st_size,existing.st_mtime_ns)==(metadata.st_size,metadata.st_mtime_ns):return False
    temporary=None
    try:
        with source.open('rb') as original:
            metadata=os.fstat(original.fileno())
            if not stat.S_ISREG(metadata.st_mode):raise ValueError('Annotation is not a regular file')
            with tempfile.NamedTemporaryFile('wb',dir=destination.parent,prefix='.'+destination.name+'-',suffix='.tmp',delete=False) as output:
                temporary=Path(output.name);copied=0
                for chunk in iter(lambda:original.read(1024**2),b''):output.write(chunk);copied+=len(chunk)
                output.flush();os.fsync(output.fileno())
        if copied!=metadata.st_size or signature(source.stat())!=signature(metadata):return False
        os.chmod(temporary,stat.S_IMODE(metadata.st_mode)&0o666)
        os.utime(temporary,ns=(metadata.st_atime_ns,metadata.st_mtime_ns))
        os.replace(temporary,destination);temporary=None
        directory=os.open(destination.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(directory)
        finally:os.close(directory)
        return True
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


OBJECTS={'bird','airplane','other_animal','insect','balloon','star','satellite','shooting_star','house','antenna','vehicle','telephone_pole','landscape','drone','tree','cloud','anomalous','unknown','no_object'}
SHAPES={'round','elongated','irregular','too_small','unresolved','unreviewed'}


def organize_classified(target,data):
    """Copies grouped by object and shape; keep prior labels if originals expire."""
    index_path=target/'classification-index.json'
    try:previous=json.loads(index_path.read_text())
    except (FileNotFoundError,ValueError):previous={}
    index={};cache={}
    for dimension,categories in (('objects',OBJECTS),('shapes',SHAPES)):
        for label in categories:
            for folder in (target/'classified',target/'classified'/dimension,target/'classified'/dimension/label):
                if folder.is_symlink():raise ValueError('Classification folders must not be symlinks')
                folder.mkdir(exist_ok=True)
    for source in sorted(target.glob('*.jpg')):
        parts=source.name.split('--')
        if len(parts)!=2 or not SID.fullmatch(parts[0]) or not BOXED.fullmatch(parts[1]):continue
        sid,name=parts;eid=name[len('motion-'):-len('-boxed.jpg')]
        if sid not in cache:
            try:cache[sid]={e['id']:e for e in json.loads((data/sid/'motion-events.json').read_text())}
            except (FileNotFoundError,ValueError,KeyError):cache[sid]={}
        event=cache[sid].get(eid,{})
        c=effective_classification(event)
        old=previous.get(source.name,{})
        if c.get('state')=='completed':
            objects={r.get('object',{}).get('label','unknown') for r in c.get('regions',[])} & OBJECTS
            shapes={r.get('shape',{}).get('label','unresolved') for r in c.get('regions',[])} & SHAPES
            entry=dict(objects=sorted(objects or ({'no_object'} if event.get('human_review',{}).get('no_object') else {'unknown'})),shapes=sorted(shapes or {'unresolved'}))
        else:entry=old or dict(objects=['unknown'],shapes=['unreviewed'])
        index[source.name]=entry
        for dimension,categories in (('objects',OBJECTS),('shapes',SHAPES)):
            for label in categories:
                directory=target/'classified'/dimension/label
                destination=directory/source.name
                if label in entry[dimension]:copy_boxed(source,destination)
                elif destination.exists() and label in old.get(dimension,[]):
                    if destination.is_symlink():raise ValueError('Classification image must not be a symlink')
                    destination.unlink(missing_ok=True)
    if index!=previous:
        with tempfile.NamedTemporaryFile('w',dir=target,prefix='.classification-',delete=False) as output:
            output.write(json.dumps(index,indent=1)+'\n');temporary=Path(output.name)
        temporary.replace(index_path)


def sync_boxed(data):
    data=Path(data);target=data/'boxed-frames'
    if target.is_symlink():raise ValueError('The boxed-frames folder must not be a symlink')
    target.mkdir(exist_ok=True,mode=0o750)
    copied=0
    for folder in sorted(data.iterdir()):
        if not SID.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():continue
        for source in folder.glob('motion-*-boxed.jpg'):
            if not BOXED.fullmatch(source.name):continue
            try:copied+=copy_boxed(source,target/(folder.name+'--'+source.name))
            except FileNotFoundError:continue
    organize_classified(target,data)
    from anomalous_events import sync_anomalous
    sync_anomalous(data)
    return copied


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path('/home/hackrf/t7/sessions'))
    parser.add_argument('--volume',type=Path,default=Path('/home/hackrf/t7'))
    parser.add_argument('--volume-id',default='S6XBNS0W321351N')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args();stop=threading.Event();waiting=False
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    while not stop.is_set():
        try:
            if not args.volume.is_mount() or (args.volume/'.field-station-volume').read_text().strip()!=args.volume_id or not args.data.resolve().is_relative_to(args.volume.resolve()):
                raise OSError('Waiting for the configured T7 volume')
            count=sync_boxed(args.data)
            if count or waiting:print(f'Boxed-frame review folder ready; copied {count} new or updated images.',flush=True)
            waiting=False
        except (OSError,ValueError) as error:
            if not waiting:print(str(error),flush=True)
            waiting=True
            if args.once:raise SystemExit(1)
        if args.once:break
        stop.wait(5)


if __name__=='__main__':main()
