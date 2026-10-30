"""Independent Apple Mail sender. A submission with uncertain outcome is never retried blindly."""
import argparse,fcntl,json,os,subprocess,time
from datetime import datetime,timezone
from pathlib import Path

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
 with tmp.open('w') as f:json.dump(value,f,allow_nan=False);f.flush();os.fsync(f.fileno())
 tmp.replace(path)

def read(path,default):
 try:return json.loads(path.read_text())
 except FileNotFoundError:return default

def compose(event):
 test=event.get('test',False)
 subject=('TEST — Field station email setup [' if test else 'Field station: anomalous candidate [')+event['id'][:12]+']'
 when=datetime.fromtimestamp(event['detected_epoch'],timezone.utc).isoformat()
 x,y,w,h=event['bounds']
 intro='This is a setup test, not an anomalous detection. The screenshot is a current camera view.' if test else 'An anomalous candidate was flagged by the station model. Human confirmation: no.'
 score='not applicable (setup test)' if test else f"{event['score']:.4f} (model score, not a calibrated probability)"
 body=intro+f'''


Detected (UTC): {when}
Generation: {event['generation']}
Frame: {event['sequence']} (source time {event['pts_seconds']:.3f} seconds)
Track: {event['track']}
Model: {event['model']}
Anomalous model score: {score}
Object bounds in native pixels: x={x}, y={y}, width={w}, height={h}
Event ID: {event['id']}

Attached: one screenshot of the detected object. {event['screenshot_description']}.
This classification is a review suggestion, not a scientifically established anomaly.
'''
 return subject,body

def preflight(sender):
 script='''on run argv
 tell application "Mail"
  repeat with a in every account
   if enabled of a and (email addresses of a contains item 1 of argv) then return "ready"
  end repeat
  error "Requested sender is not configured in Apple Mail"
 end tell
end run'''
 p=subprocess.run(['osascript','-e',script,sender],capture_output=True,text=True,timeout=30)
 if p.returncode or p.stdout.strip()!='ready':raise RuntimeError('Apple Mail sender unavailable; configure the requested address through Proton Bridge')

def deliver(folder,config,send=None,check=preflight,now=None):
 now=time.time() if now is None else now
 receipt=folder/'delivery.json';state=read(receipt,{})
 if state.get('state') in ('accepted_by_mail','submitting','uncertain','cancelled','suppressed','expired'):return state
 event=read(folder/'event.json',None)
 if not event:return {}
 if event.get('schema')!=2:
  state=dict(state='cancelled',reason='Legacy flood queue is permanently retired');save(receipt,state);return state
 if now-event['detected_epoch']>300:
  state=dict(state='expired',reason='Candidate is older than five minutes');save(receipt,state);return state
 # Global durable reservation, independent of producer grouping and track IDs.
 rate_path=folder.parent/'send-budget.json'
 with (folder.parent/'send-budget.lock').open('a') as budget_lock:
  fcntl.flock(budget_lock,fcntl.LOCK_EX)
  attempts=[t for t in read(rate_path,{}).get('attempts',[]) if now-t<86400]
  if attempts and (now-max(attempts)<1800 or len(attempts)>=4):
   state=dict(state='suppressed',reason='Hard limit: one email per 30 minutes and four per rolling 24 hours');save(receipt,state);return state
  # Reserve before contacting Mail: failures cannot release a burst of retries.
  save(rate_path,dict(attempts=[*attempts,now]))
 image=folder/event['screenshot']
 if image.parent!=folder or image.is_symlink() or not image.is_file() or image.stat().st_size>10*1024*1024:raise ValueError('Missing or invalid screenshot')
 check(config['sender']) # Safe to retry failures before any submission is attempted.
 subject,body=compose(event);(folder/'body.txt').write_text(body)
 save(receipt,dict(state='submitting',attempt_epoch=time.time(),sender=config['sender'],recipient=config['recipient']))
 try:
  if send is None:
   p=subprocess.run(['osascript',str(Path(__file__).with_name('send_mail.applescript')),config['sender'],config['recipient'],subject,str(folder/'body.txt'),str(image)],capture_output=True,text=True,timeout=60)
   if p.returncode or p.stdout.strip()!='accepted_by_mail':raise RuntimeError('Apple Mail submission did not return acceptance')
  else:send(subject,body,image)
 except Exception as exc:
  state=dict(state='uncertain',error=str(exc),updated_epoch=time.time(),note='Check Mail Sent and Outbox before retrying; no automatic duplicate submission.')
  save(receipt,state);return state
 state=dict(state='accepted_by_mail',updated_epoch=time.time(),sender=config['sender'],recipient=config['recipient'],note='Mail accepted the message; inbox delivery is not independently confirmed.')
 save(receipt,state);return state

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args();config=read(args.config,{})
 root=Path(config['outbox']).resolve();root.mkdir(parents=True,exist_ok=True)
 with (root/'sender.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  while True:
   counts={};error=None
   for marker in sorted(root.glob('*/event.json')):
    try:
     state=deliver(marker.parent,config);key=state.get('state','pending');counts[key]=counts.get(key,0)+1
    except Exception as exc:error=str(exc);break
   save(root/'sender-status.json',dict(updated_epoch=time.time(),counts=counts,error=error))
   if args.once:break
   time.sleep(10)
if __name__=='__main__':main()
