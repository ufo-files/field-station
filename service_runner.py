"""Keep field services on their verified external volume, with idle sleep inhibited."""
import json,os,signal,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parent;role=sys.argv[1]
print('Starting field service',role,'loading environment',flush=True)
env=dict(os.environ,**json.loads((root/'environment.json').read_text()))
print('Checking external SSD permission',flush=True)
volume=Path(env['CAPTURE_VOLUME']);marker=volume/'.field-station-volume'
while True:
 try:
  if volume.is_mount() and marker.read_text().strip()==env['CAPTURE_VOLUME_ID']:break
 except OSError:pass
 print('Waiting for verified field SSD',flush=True);time.sleep(5)
print('External SSD verified',flush=True)
args=json.loads((root/'services.json').read_text())[role]
child=subprocess.Popen(args,env=env)
def stop(*_):
 if child.poll() is None:child.send_signal(signal.SIGTERM)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
awake=subprocess.Popen(['/usr/bin/caffeinate','-i','-m','-w',str(child.pid)]) if role=='capture' else None
try:raise SystemExit(child.wait())
finally:
 if awake and awake.poll() is None:awake.terminate()
