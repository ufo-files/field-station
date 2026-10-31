"""Bind an explicit owner's reply to a sent alert and preserve auditable native-crop labels."""
import hashlib,json,re,shutil,subprocess,time
from email import policy
from email.parser import Parser
from email.utils import parseaddr
from pathlib import Path
from mail_alerts import read,save
LABELS={'anomalous','airplane','bird','insect','cloud','tree','other_animal','balloon','star','satellite','shooting_star','house','antenna','vehicle','telephone_pole','mountain','landscape','drone','unknown'}
ALIASES={'landscapes':'landscape','mountains':'mountain','telephone pole':'telephone_pole','telephone poles':'telephone_pole','utility pole':'telephone_pole','utility poles':'telephone_pole','power pole':'telephone_pole','power poles':'telephone_pole','houses':'house','antennas':'antenna','vehicles':'vehicle','car':'vehicle','cars':'vehicle','truck':'vehicle','trucks':'vehicle','shooting star':'shooting_star','shooting stars':'shooting_star','meteor':'shooting_star','meteors':'shooting_star','satellites':'satellite','stars':'star','plane':'airplane','aircraft':'airplane','bug':'insect','other animal':'other_animal'}

def parse_reply(body):
 lines=[line.strip() for line in body.splitlines() if line.strip()]
 if not lines:return None
 first=lines[0].lower().strip().rstrip('.!').strip()
 if first=='yes':return 'anomalous'
 if first=='no':return 'not_anomalous'
 match=re.fullmatch(r'no[\s,:-]+([a-z_ ]+)',first)
 value=match[1].strip() if match else first
 label=ALIASES.get(value,value)
 allowed=LABELS-{'anomalous'} if match else LABELS
 return label if label in allowed else None

def normalized_ids(value):return set(re.findall(r'<([^<>]+)>',value))

def ingest(message,config):
 if parseaddr(message.get('sender',''))[1].lower()!=config['recipient'].lower():return 'ignored_sender'
 match=re.search(r'\[([a-f0-9]{12})\]',message.get('subject',''))
 if not match:return 'ignored_subject'
 headers=Parser(policy=policy.default).parsestr(message.get('headers',''))
 references=normalized_ids(str(headers.get('In-Reply-To',''))+' '+str(headers.get('References','')))
 sent={s.strip('<>') for s in message.get('sent_message_ids',[])}
 if not references.intersection(sent):return 'ignored_unlinked_reply'
 auth=' '.join(str(v).lower() for v in headers.get_all('Authentication-Results',[]))
 if 'dmarc=fail' in auth or ('dkim=fail' in auth and 'dkim=pass' not in auth):return 'ignored_failed_authentication'
 label=parse_reply(message.get('content',''))
 if label is None:return 'ignored_ambiguous_reply'
 root=Path(config['outbox']);matches=[p for p in root.glob(match[1]+'*/event.json') if len(p.parent.name)==32]
 if len(matches)!=1:return 'ignored_missing_or_ambiguous_event'
 folder=matches[0].parent;event=read(matches[0],{})
 receipt=read(folder/'delivery.json',{})
 if event.get('test') or receipt.get('state')!='accepted_by_mail':return 'ignored_unsent_or_test'
 mid=message.get('message_id','').strip('<>')
 if not mid:return 'ignored_missing_message_id'
 crop=folder/(event.get('native_crop') or ('object.png' if event.get('schema')==1 else 'native-object.png'))
 if crop.parent!=folder or crop.is_symlink() or not crop.is_file():return 'waiting_for_native_crop'
 digest=hashlib.sha256(crop.read_bytes()).hexdigest()
 if event.get('native_crop_sha256') and digest!=event['native_crop_sha256']:raise ValueError('Original alert crop changed')
 import sys
 sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'uap-lab'))
 from email_training import store_review
 record=dict(schema=1,event_id=event['id'],message_id=mid,reviewed_epoch=float(message['received_epoch']),label=label,human_confirmed=True,source='owner_email_reply',generation=event['generation'],sequence=event['sequence'],pts_seconds=event['pts_seconds'],bounds=event['bounds'],model=event['model'],native_crop_sha256=digest,binary_anomalous=label=='anomalous',multiclass_ready=label!='not_anomalous',reviewer=config['recipient'])
 return store_review(config['lab_data'],record,crop.read_bytes())

def poll(config):
 root=Path(config['lab_data'])/'email-reviews';seen=read(root/'scanned-message-ids-category-replies.json',[])
 known=set(seen)
 for path in (root/'history').glob('*.json'):
  row=read(path,{})
  if row.get('source')=='owner_email_reply':known.add(row['message_id'].strip('<>'))
 p=subprocess.run(['osascript','-l','JavaScript',str(Path(__file__).with_name('read_replies.js')),config['recipient'],json.dumps(sorted(known))],capture_output=True,text=True,timeout=45)
 if p.returncode:raise RuntimeError('Mail reply reader failed: '+p.stderr.strip()[-400:])
 counts={}
 for message in sorted(json.loads(p.stdout),key=lambda m:m['received_epoch']):
  state=ingest(message,config);counts[state]=counts.get(state,0)+1
  if state in ('imported','already_imported','ignored_sender','ignored_subject','ignored_failed_authentication','ignored_ambiguous_reply'):
   known.add(message['message_id'].strip('<>'))
 save(root/'scanned-message-ids-category-replies.json',sorted(known))
 save(Path(config['lab_data'])/'email-reviews/status.json',dict(updated_epoch=time.time(),counts=counts,error=None))
 return counts
