"""Persistent silent YouTube composite encoder, supervised by launchd."""
import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import signal
import subprocess
import threading
import time
from pathlib import Path
from broadcast_camera import CameraPipe
from broadcast_rf import OverlayPipe
from youtube_broadcast import broadcast_args

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    options=parser.parse_args()
    config=json.loads(options.config.read_text())
    if config.get('enabled') is not True:
        return 0
    root=options.config.parent
    lock=(root/'continuous.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    log=logging.getLogger('youtube')
    log.setLevel(logging.INFO)
    log.addHandler(RotatingFileHandler(root/'continuous.log', maxBytes=1024*1024, backupCount=2))
    config['continuous']=True
    camera=CameraPipe(config['source'], Path(__file__).with_name('assets')/'broadcast-standby.jpg')
    overlay=OverlayPipe(config.get('rf_path','/Volumes/UFO-Field/signal-spool/live.json'), camera=camera)
    stop=threading.Event()
    last_progress=[time.monotonic()]
    started=time.time()
    def status(state, metrics=None):
        data={'state':state,'updated_epoch':time.time(),'started_epoch':started,'camera_standby':camera.current()[1],'audio':'silent','metrics':metrics or {}}
        temp=root/'continuous-status.tmp'
        temp.write_text(json.dumps(data))
        temp.replace(root/'continuous-status.json')
    proc=None
    def shutdown(*unused):
        stop.set()
        if proc is not None and proc.poll() is None:
            proc.terminate()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        proc=subprocess.Popen(broadcast_args(config,overlay.reader,camera_fd=camera.reader),pass_fds=(camera.reader,overlay.reader),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def errors():
            for line in proc.stderr:
                log.warning(line.rstrip().replace(config['publish_url'],'[YouTube ingest]').replace(config['publish_url'].rsplit('/',1)[-1],'[stream key]'))
        def watchdog():
            while not stop.wait(2):
                if time.monotonic()-last_progress[0]>45:
                    log.error('Encoder stopped advancing; restarting through launchd')
                    shutdown()
                    break
            if proc.poll() is None:
                try:proc.wait(timeout=8)
                except subprocess.TimeoutExpired:proc.kill()
        threading.Thread(target=errors,daemon=True).start()
        threading.Thread(target=watchdog,daemon=True).start()
        camera.start();overlay.start();status('starting');log.info('Starting continuous silent camera/RF broadcast')
        metrics={};last_saved=0
        for line in proc.stdout:
            key,sep,value=line.strip().partition('=')
            if sep:metrics[key]=value
            if key=='progress':
                if int(metrics.get('frame','0'))>int(getattr(main,'last_frame',-1)):
                    last_progress[0]=time.monotonic();main.last_frame=int(metrics.get('frame','0'))
                if time.monotonic()-last_saved>=5:
                    status('streaming',metrics);last_saved=time.monotonic()
        result=proc.wait()
        status('stopped',metrics);log.info('Encoder exited with status %s',result)
        return result
    finally:
        shutdown()
        if proc is not None and proc.poll() is None:
            try:proc.wait(timeout=8)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        camera.close();overlay.close();lock.close()

if __name__=='__main__':
    raise SystemExit(main())
