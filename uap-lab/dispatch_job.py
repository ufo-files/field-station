"""Persistent field-side dispatcher, separate from the web app."""
import json,os,sys,fcntl
from pathlib import Path
root=Path(__file__).resolve().parent
os.environ.update(json.loads((root.parent/'environment.json').read_text()))
import lab
rid=lab.checked_id(sys.argv[1]);folder=lab.DATA/'runs'/rid;r=lab.read(folder/'run.json');model=lab.read(folder/'model.json')
with (folder/'dispatcher.lock').open('a') as lease:
    try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:sys.exit(0)
    lab.evaluate(rid,r['video_id'],model,r['threshold'],r['labels'])
