"""Independent local analysis service; HTTP/UI and model search cannot block its loop."""
import os,signal,threading,time
import cv2
import lab
cv2.setNumThreads(2)
from live_monitor import LiveMonitor
from native_capture import NativeCapture
from spool_export import watch as export_watch
from spool_gc import watch as retention_watch
from qualification import watch as qualification_watch
monitor=LiveMonitor(start_workers=False)
monitor.model_id=(lab.read(lab.DATA/'active-model.json') or {}).get('id')
root=os.environ['CAPTURE_BUFFER_ROOT']
def stop(*args):monitor.stop_event.set()
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
threading.Thread(target=export_watch,args=(root,),daemon=True).start()
threading.Thread(target=retention_watch,args=(root,monitor.stop_event),daemon=True).start()
threading.Thread(target=qualification_watch,args=(lab.DATA,os.environ['RF_LIVE_PATH'],monitor.stop_event),daemon=True).start()
if not lab.read(lab.ROOT/'recognition/config.json',{}).get('event_owner'):
    engine=NativeCapture(monitor);engine.start()
while not monitor.stop_event.wait(5):
    monitor.model_id=(lab.read(lab.DATA/'active-model.json') or {}).get('id')
    monitor.config=lab.read(monitor.folder/'config.json',monitor.config)
