"""Reconnectable private archive transport, initiated by the main station."""
import argparse,json,os
from pathlib import Path

def main(cfg):
 values={}
 for line in Path(cfg['credentials']).read_text().splitlines():
  key,sep,value=line.partition(':')
  if sep:values[key.strip().lower()]=value.strip()
 env=os.environ.copy();env.update(SSH_ASKPASS=cfg['askpass'],SSH_ASKPASS_REQUIRE='force',DISPLAY='archive-tunnel')
 remote_port=int(cfg.get('archive_remote_port',18094));local_port=int(cfg.get('archive_local_port',8094))
 if not 1024<=remote_port<=65535 or not 1024<=local_port<=65535:raise ValueError('Invalid archive tunnel port')
 args=['ssh','-N','-T','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3','-o','ConnectTimeout=15','-o','NumberOfPasswordPrompts=1','-o','StrictHostKeyChecking=accept-new','-R',f'127.0.0.1:{remote_port}:127.0.0.1:{local_port}',values['username']+'@'+values['ip']]
 os.execvpe('/usr/bin/ssh',args,env)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=Path.home()/'field-migration/field-replica.json');args=parser.parse_args();main(json.loads(args.config.read_text()))
