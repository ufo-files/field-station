#!/usr/bin/env python3
"""Mac hardware live encoder; configuration arrives privately over SSH stdin."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


def live_args(config):
    url=config['publish_url'];host=urlsplit(url).hostname or ''
    if urlsplit(url).scheme!='rtmps' or not host.endswith('.youtube.com'):
        raise ValueError('Expected encrypted YouTube ingestion endpoint')
    return ['/opt/homebrew/bin/ffmpeg','-hide_banner','-loglevel','warning','-nostdin',
        '-rw_timeout','15000000','-use_wallclock_as_timestamps','1','-f','mpjpeg','-i',config['source'],
        '-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100',
        '-t',str(config.get('duration_seconds',600)),'-map','0:v:0','-map','1:a:0',
        '-vf','scale=1280:720,setsar=1','-c:v','h264_videotoolbox','-b:v','4000k',
        '-maxrate','4000k','-bufsize','8000k','-g','60','-pix_fmt','yuv420p','-r','30',
        '-c:a','aac','-b:a','128k','-ar','44100','-f','flv',url]


def main():
    config=json.loads(sys.stdin.readline());root=Path.home()/'Library/Caches/field-station'
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (root/'encode.lock').open('a') as lock:
        # Prioritize an uninterrupted live test over new bulk source transfers.
        fcntl.flock(lock,fcntl.LOCK_EX)
        with subprocess.Popen(live_args(config),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True) as proc:
            for line in proc.stderr:
                print(line.replace(config['publish_url'],'[YouTube ingest]').replace(config['publish_url'].rsplit('/',1)[-1],'[stream key]'),end='',flush=True)
            raise SystemExit(proc.wait())

if __name__=='__main__':main()
