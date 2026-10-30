#!/usr/bin/env python3
"""Replace this process with a key-authenticated SSH job owned by the Pi."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

ROOT=Path(__file__).resolve().parent


def ssh_args(config):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+',config['host']) or not re.fullmatch(r'[a-zA-Z0-9_.-]+',config['username']):
        raise ValueError('Invalid worker host or username')
    return ['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=15','-o','ServerAliveInterval=15',
        '-o','ServerAliveCountMax=3','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+str(ROOT/'private/m1/known_hosts'),'-i',str(ROOT/'private/m1/id_ed25519'),
        config['username']+'@'+config['host']]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('target',type=Path);args=p.parse_args()
    config=json.loads((ROOT/'private/m1/config.json').read_text())
    if not config.get('enabled'):raise ValueError('M1 worker is disabled')
    digest=hashlib.sha256()
    with args.source.open('rb') as source:
        for block in iter(lambda:source.read(1024**2),b''):digest.update(block)
    command=' '.join(shlex.quote(s) for s in ['/usr/bin/python3',config['worker'],'--bytes',str(args.source.stat().st_size),'--sha256',digest.hexdigest()])
    with args.source.open('rb') as source,args.target.open('wb') as target:
        os.dup2(source.fileno(),0);os.dup2(target.fileno(),1)
    os.execvp('ssh',ssh_args(config)+[command])

if __name__=='__main__':main()
