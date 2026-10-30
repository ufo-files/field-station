#!/usr/bin/env python3
"""Clear ALL data on the explicitly authorized T7; retain mount/configuration."""
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import time

SERIAL='S6XBNS0W321351N'
UUID='a8ec8f1e-b658-4182-87b4-34b56cf70a5b'
MOUNT=Path('/home/hackrf/t7')
ROOT=Path('/home/hackrf/capture-station')
MARKER='.field-station-volume'
UNITS=('field-station-recovery.timer','field-station-recovery.service',
       'hackrf-signal-publish.timer','hackrf-signal-publish.service',
       'hackrf-signal-logger.service','smbd.service')


def command(*args,check=True):
    return subprocess.run(args,check=check,capture_output=True,text=True)


def verify_volume():
    if MOUNT.is_symlink() or not MOUNT.is_mount():
        raise RuntimeError('T7 mount missing; nothing will be deleted.')
    data=json.loads(command('findmnt','--json','--mountpoint',str(MOUNT),'-o','TARGET,UUID').stdout)
    mounts=data.get('filesystems',[])
    if len(mounts)!=1 or mounts[0].get('uuid')!=UUID:
        raise RuntimeError('Wrong filesystem UUID; nothing will be deleted.')
    if (MOUNT/MARKER).is_symlink() or (MOUNT/MARKER).read_text().strip()!=SERIAL:
        raise RuntimeError('Wrong T7 marker; nothing will be deleted.')
    nested=json.loads(command('findmnt','--json','--submounts','--mountpoint',str(MOUNT),'-o','TARGET').stdout)
    if any(item.get('children') for item in nested.get('filesystems',[])):
        raise RuntimeError('Nested mounted filesystems found; refusing cleanup.')


def clear_contents(volume,verify):
    """Never follow a top-level symlink outside the recording drive."""
    for entry in list(volume.iterdir()):
        verify()
        if entry.name==MARKER:continue
        print('Deleting',entry.name,flush=True)
        if entry.is_symlink() or not entry.is_dir():entry.unlink()
        else:shutil.rmtree(entry)


def user_systemctl(account,*args,check=True):
    return command('runuser','-u',account.pw_name,'--','env',
        f'XDG_RUNTIME_DIR=/run/user/{account.pw_uid}',
        f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{account.pw_uid}/bus',
        'systemctl','--user',*args,check=check)


def write_audit(path,value,account):
    temp=path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    os.chown(temp,account.pw_uid,account.pw_gid);temp.replace(path)


def main():
    if sys.argv[1:]!=['--clear-'+SERIAL]:
        raise SystemExit('Use --clear-'+SERIAL+' to clear ALL data on this T7 only.')
    if os.geteuid()!=0:raise SystemExit('Run this command with sudo in the Pi terminal.')
    verify_volume()
    account=pwd.getpwnam('hackrf')
    before=shutil.disk_usage(MOUNT)
    active=[u for u in UNITS if command('systemctl','is-active','--quiet',u,check=False).returncode==0]
    app_active=user_systemctl(account,'is-active','capture-station.service',check=False).stdout.strip()=='active'
    audit=ROOT/'run'/f'clear-t7-{int(time.time())}.json'
    record=dict(serial=SERIAL,uuid=UUID,started_epoch=time.time(),state='stopping_writers',
        used_before=before.used,services_before=active,app_active=app_active)
    write_audit(audit,record,account)
    # Stop retry automation first, then all processes capable of writing the SSD.
    for unit in ('field-station-recovery.timer','field-station-recovery.service'):
        if unit in active:command('systemctl','stop',unit)
    user_systemctl(account,'stop','capture-station.service')
    for unit in ('hackrf-signal-publish.timer','hackrf-signal-publish.service','hackrf-signal-logger.service','smbd.service'):
        if unit in active:command('systemctl','stop',unit)
    verify_volume()
    record['state']='clearing';write_audit(audit,record,account)
    try:
        clear_contents(MOUNT,verify_volume)
        verify_volume()
        for name in ('sessions','signal-spool','experiment-audio','Uploads'):
            path=MOUNT/name;path.mkdir(mode=0o770)
            os.chown(path,account.pw_uid,account.pw_gid)
        (MOUNT/'lost+found').mkdir(mode=0o700)
        # Forget links to removed evidence, while retaining thresholds and borders.
        for name in ('motion-trigger-last-event.json','rf-trigger-last-event.json','rf-trigger-pending.json'):
            (ROOT/'run'/name).unlink(missing_ok=True)
        automatic=ROOT/'run/automatic.json'
        if automatic.exists():
            config=json.loads(automatic.read_text())
            config.update(last_session=None,next_session_epoch=None,next_condition='silence',cycle_settings=None)
            if config.get('ce5_enabled'):
                config['ce5_enabled']=False
                print('CE5 files removed; CE5 playback disabled until re-uploaded.',flush=True)
            write_audit(automatic,config,account)
        os.sync()
        # Restart the timer, not an in-flight pre-cleanup publisher invocation.
        for unit in ('hackrf-signal-logger.service','smbd.service','hackrf-signal-publish.timer'):
            if unit in active:command('systemctl','start',unit)
        if app_active:user_systemctl(account,'start','capture-station.service')
        if 'field-station-recovery.timer' in active:command('systemctl','start','field-station-recovery.timer')
        after=shutil.disk_usage(MOUNT)
        record.update(state='completed',finished_epoch=time.time(),used_after=after.used,free_after=after.free)
        write_audit(audit,record,account)
        print(f'T7 cleared. Available: {after.free/1024**3:.1f} GiB. Station settings retained.',flush=True)
    except BaseException as error:
        record.update(state='failed',error=str(error));write_audit(audit,record,account)
        print('Cleanup or service restart did not finish. Inspect the audit and rerun the same command.',file=sys.stderr)
        raise

if __name__=='__main__':main()
