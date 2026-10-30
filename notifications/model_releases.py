"""One release notice per successfully deployed model, through the existing Mail worker."""
import subprocess,time
from datetime import datetime,timezone
from pathlib import Path
from mail_alerts import read,save,preflight

def compose(release):
 when=datetime.fromtimestamp(release['deployed_epoch'],timezone.utc).isoformat()
 labels=', '.join(f'{label.replace("_"," ")}: {count}' for label,count in sorted(release.get('labels',{}).items())) or 'See training audit'
 return ('Field station: new model released ['+release['version'][:12]+']',
  f'A new field-station model was released at {when} (UTC).\n\n'
  'It passed held-out accuracy checks, station runtime checks, and live recognition health checks.\n\n'
  f'Model: {release["version"]}\nPrevious model: {release["previous_version"]}\n'
  f'Reviewed labels in this training snapshot: {labels}\n\n'
  'Your saved corrections were included in training. These checks do not guarantee that every future cloud will be classified correctly.\n')

def deliver(folder,config,send=None,check=preflight):
 receipt=folder/'delivery.json';state=read(receipt,{})
 if state.get('state') in ('accepted_by_mail','submitting','uncertain'):return state
 release=read(folder/'release.json',{})
 if release.get('state')!='deployed' or not release.get('health_verified'):raise ValueError('Release has not passed deployment health checks')
 subject,body=compose(release);check(config['sender']);(folder/'body.txt').write_text(body)
 save(receipt,dict(state='submitting',attempt_epoch=time.time()))
 try:
  if send is None:
   result=subprocess.run(['osascript',str(Path(__file__).with_name('send_release.applescript')),config['sender'],config['recipient'],subject,str(folder/'body.txt')],capture_output=True,text=True,timeout=60)
   if result.returncode or result.stdout.strip()!='accepted_by_mail':raise RuntimeError('Release notice acceptance uncertain')
  else:send(subject,body)
  state=dict(state='accepted_by_mail',updated_epoch=time.time(),sender=config['sender'],recipient=config['recipient'])
 except Exception as exc:state=dict(state='uncertain',updated_epoch=time.time(),error=str(exc))
 save(receipt,state);return state

def poll(config):
 root=Path(config['outbox']).parent/'model-releases'
 for marker in sorted(root.glob('*/release.json')):deliver(marker.parent,config)
