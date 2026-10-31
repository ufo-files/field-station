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

def compose(event,config=None):
 test=event.get('test',False)
 subject=('TEST — Field station email setup [' if test else 'Field station: anomalous candidate [')+event['id'][:12]+']'
 when=datetime.fromtimestamp(event['detected_epoch'],timezone.utc).isoformat()
 x,y,w,h=event['bounds']
 base=(config or {}).get('review_base_url','').rstrip('/')
 review_link=(base+'/email-review?id='+event['id']) if base else 'Review link is not configured.'
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

Watch the surrounding video, scrub, redraw the box, and relabel:
{review_link}

Attachments: two images. {event['screenshot_description']}.

Reply YES to label the object anomalous, or simply reply with its correct category: insect, airplane, bird, cloud, tree, balloon, star, satellite, shooting star, drone, other animal, or unknown. The category alone corrects the label; NO is not required. Replies such as NO CLOUD still work. A plain NO is a negative anomaly example without a species/class label. Punctuation is fine. Your reply labels this object's clean native crop for training.
This classification is a review suggestion, not a scientifically established anomaly.
'''
 return subject,body

def require_review_link(event,config,body):
 from urllib.parse import urlsplit
 base=config.get('review_base_url','').rstrip('/');url=base+'/email-review?id='+event['id'];parsed=urlsplit(base)
 if parsed.scheme not in ('http','https') or not parsed.netloc or url not in body:raise ValueError('Refusing to send an alert without its review link')
 return url

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
 from release_backlog import cancel_if_obsolete,latest
 obsolete=cancel_if_obsolete(folder,event,latest(config))
 if obsolete:return obsolete
 if event.get('schema')!=3:
  state=dict(state='cancelled',reason='Legacy flood queue is permanently retired');save(receipt,state);return state
 if config.get('lab_data'):
  import sys
  sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'uap-lab'))
  from email_review import prepare
  if prepare(config['lab_data'],event['id']).get('state')!='ready':return dict(state='preparing_video')
 images=[folder/name for name in event.get('screenshots',[])]
 if len(images)!=2 or len(set(images))!=2:raise ValueError('Exactly two distinct attachments required')
 for image in images:
  if image.parent!=folder or image.is_symlink() or not image.is_file() or image.stat().st_size>10*1024*1024:raise ValueError('Missing or invalid screenshot')
 check(config['sender']) # Safe to retry failures before any submission is attempted.
 subject,body=compose(event,config);review_link=require_review_link(event,config,body);(folder/'body.txt').write_text(body)
 obsolete=cancel_if_obsolete(folder,event,latest(config))
 if obsolete:return obsolete
 save(receipt,dict(state='submitting',attempt_epoch=time.time(),sender=config['sender'],recipient=config['recipient']))
 try:
  if send is None:
   p=subprocess.run(['osascript',str(Path(__file__).with_name('send_mail.applescript')),config['sender'],config['recipient'],subject,str(folder/'body.txt'),*[str(image) for image in images],review_link],capture_output=True,text=True,timeout=60)
   if p.returncode or p.stdout.strip()!='accepted_by_mail':raise RuntimeError('Apple Mail submission did not return acceptance')
  else:send(subject,body,images)
 except Exception as exc:
  state=dict(state='uncertain',error=str(exc),updated_epoch=time.time(),note='Check Mail Sent and Outbox before retrying; no automatic duplicate submission.')
  save(receipt,state);return state
 state=dict(state='accepted_by_mail',updated_epoch=time.time(),sender=config['sender'],recipient=config['recipient'],note='Mail accepted the message; inbox delivery is not independently confirmed.')
 save(receipt,state)
 try:
  import sys
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'uap-lab'))
  from queue_index import touch
  touch(folder.parent,folder.name)
 except Exception:pass # A display-index failure must never resend accepted mail.
 return state

def send_requested_update(config):
 """One operator-authorized resend; does not duplicate an existing requested update."""
 key=config.get('requested_update_event')
 if not key:return
 import re
 if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid requested update')
 revision=config.get('requested_update_revision','')
 if revision and not re.fullmatch('[a-z0-9-]{1,40}',revision):raise ValueError('Invalid requested update revision')
 folder=Path(config['outbox'])/key;receipt=folder/('requested-update'+('-'+revision if revision else '')+'-delivery.json')
 if receipt.exists():return
 event=read(folder/'event.json',{});images=[folder/name for name in event['screenshots']]
 if event.get('schema')!=3 or len(images)!=2 or any(p.parent!=folder or p.is_symlink() or not p.is_file() for p in images):raise ValueError('Updated alert images missing')
 preflight(config['sender']);subject,body=compose(event,config);review_link=require_review_link(event,config,body)
 subject=subject.replace('anomalous candidate','video review')
 (folder/'requested-update-body.txt').write_text('Review video and relabel:\n'+review_link+'\n\nRequested updated alert: this is the earlier recorded candidate, not a new detection.\n\n'+body)
 save(receipt,dict(state='submitting',requested_by='user',attempt_epoch=time.time()))
 try:
  p=subprocess.run(['osascript',str(Path(__file__).with_name('send_mail.applescript')),config['sender'],config['recipient'],subject,str(folder/'requested-update-body.txt'),*[str(i) for i in images],review_link],capture_output=True,text=True,timeout=60)
  if p.returncode or p.stdout.strip()!='accepted_by_mail':raise RuntimeError('Requested update acceptance uncertain')
  save(receipt,dict(state='accepted_by_mail',updated_epoch=time.time(),requested_by='user',attachments=2))
  save(folder/'delivery.json',dict(state='accepted_by_mail',updated_epoch=time.time(),requested_by='user',sender=config['sender'],recipient=config['recipient']))
 except Exception as exc:save(receipt,dict(state='uncertain',error=str(exc),updated_epoch=time.time()))

def poll_release_notices(config):
 try:
  from release_backlog import clear
  clear(config)
  from model_releases import poll
  poll(config)
 except Exception as exc:save(Path(config['outbox'])/'release-notice-error.json',dict(updated_epoch=time.time(),error=str(exc)))

def poll_replies_if_due(config,last_poll):
 if config.get('lab_data') and time.monotonic()-last_poll>=60:
  try:
   from reply_reviews import poll
   poll(config)
  except Exception as exc:
   save(Path(config['lab_data'])/'email-reviews/status.json',dict(updated_epoch=time.time(),error=str(exc)))
  return time.monotonic()
 return last_poll

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args();config=read(args.config,{})
 root=Path(config['outbox']).resolve();root.mkdir(parents=True,exist_ok=True)
 with (root/'sender.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  last_reply_poll=0
  while True:
   try:send_requested_update(config)
   except Exception as exc:save(root/'requested-update-error.json',dict(error=str(exc),updated_epoch=time.time()))
   poll_release_notices(config)
   last_reply_poll=poll_replies_if_due(config,last_reply_poll)
   counts={};error=None
   for marker in sorted(root.glob('*/event.json')):
    poll_release_notices(config)
    last_reply_poll=poll_replies_if_due(config,last_reply_poll)
    try:
     state=deliver(marker.parent,config);key=state.get('state','pending');counts[key]=counts.get(key,0)+1
    except Exception as exc:error=str(exc);break
   save(root/'sender-status.json',dict(updated_epoch=time.time(),counts=counts,error=error))
   if args.once:break
   time.sleep(10)
if __name__=='__main__':main()
