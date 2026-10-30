"""Preserve an active recording before restarting the camera station."""
import json,subprocess,time,urllib.request
base='http://localhost:8090'
def status():return json.load(urllib.request.urlopen(base+'/api/status',timeout=60))
s=status()
if s['active']:
 print('Finalizing active recording before update:',s['active']['id'],flush=True)
 request=urllib.request.Request(base+'/api/stop',data=b'{}',headers={'Content-Type':'application/json','X-Station-Token':s['csrf']})
 json.load(urllib.request.urlopen(request,timeout=120))
subprocess.run(['systemctl','--user','restart','capture-station.service'],check=True)
subprocess.run(['systemctl','--user','restart','boxed-frames.service'],check=True)
time.sleep(3);print('Camera fresh:',status()['camera']['fresh'],flush=True)
