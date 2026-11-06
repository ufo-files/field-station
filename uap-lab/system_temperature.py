"""On-demand, cached Apple Silicon temperature samples; no disk history."""
import json,math,os,subprocess,threading,time
from pathlib import Path

class Temperature:
 def __init__(self):
  self.lock=threading.Lock();self.value=None;self.measured=0;self.next_sample=0;self.running=False
 def read(self):
  runtime=Path(os.environ.get('XDG_RUNTIME_DIR','/tmp'))
  binary=os.environ.get('MACMON',str(runtime/'tools/macmon-0.10.0/macmon'))
  result=subprocess.run([binary,'pipe','-s','1','-i','1000'],capture_output=True,text=True,timeout=5,check=True)
  value=json.loads(result.stdout.strip().splitlines()[-1]).get('temp',{}).get('cpu_temp_avg')
  if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<150:raise ValueError('Temperature unavailable')
  return round(value,1)
 def sample(self):
  try:value=self.read()
  except (OSError,ValueError,IndexError,subprocess.SubprocessError):value=None
  with self.lock:
   self.value=value;self.measured=time.monotonic();self.running=False
 def snapshot(self):
  with self.lock:
   now=time.monotonic()
   if not self.running and now>=self.next_sample:
    self.running=True;self.next_sample=now+15;threading.Thread(target=self.sample,daemon=True).start()
   fresh=self.value is not None and now-self.measured<=45
   return dict(available=fresh,celsius=self.value if fresh else None,sensor='CPU',sampling=self.running)

MONITOR=Temperature()
def status():return MONITOR.snapshot()
