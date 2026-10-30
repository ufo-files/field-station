#!/usr/bin/env python3
"""SSH-only Mac encoding worker. Receives originals; returns a verified MP4."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

FFMPEG='/opt/homebrew/bin/ffmpeg'
FFPROBE='/opt/homebrew/bin/ffprobe'


def encode(size,expected_hash,root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (root/'encode.lock').open('a') as lock:
        if size<=0 or shutil.disk_usage(root).free < size*2+20*1024**3:
            raise OSError('M1 needs room for input/output plus 20 GiB reserve')
        with tempfile.TemporaryDirectory(prefix='job-',dir=root) as folder:
            source=Path(folder)/'source.mkv';target=Path(folder)/'video.mp4';digest=hashlib.sha256();remaining=size
            with source.open('wb') as output:
                while remaining:
                    chunk=sys.stdin.buffer.read(min(1024**2,remaining))
                    if not chunk:raise OSError('Incomplete source transfer')
                    output.write(chunk);digest.update(chunk);remaining-=len(chunk)
            if digest.hexdigest()!=expected_hash:raise OSError('Source checksum mismatch')
            fcntl.flock(lock,fcntl.LOCK_EX)
            began=time.monotonic()
            # Keep the station's existing CRF18 archival quality policy.
            subprocess.run([FFMPEG,'-hide_banner','-loglevel','warning','-nostdin','-y','-i',str(source),
                '-map','0:v:0','-vf','setsar=1','-c:v','libx264','-preset','ultrafast','-crf','18','-threads','4',
                '-pix_fmt','yuv420p','-profile:v','high','-level:v','4.2','-fps_mode','passthrough',
                '-movflags','+faststart',str(target)],check=True,stdout=sys.stderr)
            print('M1 encode seconds: %.2f'%(time.monotonic()-began),file=sys.stderr,flush=True)
            with target.open('rb') as video:shutil.copyfileobj(video,sys.stdout.buffer,1024**2)
            sys.stdout.buffer.flush()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bytes',type=int,required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--root',default=str(Path.home()/'Library/Caches/field-station'))
    args=parser.parse_args();os.umask(0o077)
    encode(args.bytes,args.sha256,args.root)

if __name__=='__main__':main()
