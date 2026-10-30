#!/usr/bin/env python3
"""Safely disconnect/reconnect the recording SSD without erasing any data."""
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
MOUNT = Path('/home/hackrf/t7')
STATE = ROOT/'run/t7-cable-swap.json'
SERVICES = ('hackrf-signal-logger.service', 'hackrf-signal-publish.timer', 'smbd.service')

def run(*args):
    subprocess.run(args, check=True)

def status():
    with urlopen('http://127.0.0.1:8090/api/status', timeout=10) as response:
        return json.load(response)

def main():
    if os.geteuid()!=0 or sys.argv[1:] not in (['unmount'], ['resume']):
        raise SystemExit('Run with sudo and either unmount or resume. This never formats the SSD.')
    account = pwd.getpwnam('hackrf')
    if sys.argv[1]=='unmount':
        s = status()
        if s['active'] or s['experiments']['processing'] or s['experiments']['queued']:
            raise SystemExit('A recording/export is active. Leave the SSD connected and wait.')
        if subprocess.run(['systemctl','is-active','--quiet','hackrf-signal-publish.service']).returncode==0:
            raise SystemExit('An RF upload is active. Leave the SSD connected and retry after it completes.')
        if not MOUNT.is_mount() or (MOUNT/'.field-station-volume').read_text().strip()!='S6XBNS0W321351N':
            raise SystemExit('Expected T7 mount not found. Leave connected for inspection.')
        saved = dict(automatic=s['experiments']['automatic'], rf_trigger=s.get('rf_trigger'), motion_trigger=s.get('motion_trigger'), unmounted=False,
                     services=[name for name in SERVICES if subprocess.run(['systemctl','is-active','--quiet',name]).returncode==0])
        STATE.write_text(json.dumps(saved,indent=2))
        os.chown(STATE, account.pw_uid, account.pw_gid)
        with urlopen(Request('http://127.0.0.1:8090/api/automatic/disable',data=b'{}',
                headers={'Content-Type':'application/json','X-Station-Token':s['csrf']})) as response:
            response.read()
        if s.get('rf_trigger'):
            with urlopen(Request('http://127.0.0.1:8090/api/rf-trigger/configure',data=b'{"enabled":false}',
                    headers={'Content-Type':'application/json','X-Station-Token':s['csrf']})) as response:
                response.read()
        if s.get('motion_trigger'):
            with urlopen(Request('http://127.0.0.1:8090/api/motion-trigger/configure',data=b'{"enabled":false}',
                    headers={'Content-Type':'application/json','X-Station-Token':s['csrf']})) as response:
                response.read()
        if status()['active']:
            raise SystemExit('A recording just started. Leave connected and wait for it to finish.')
        run('systemctl','stop',*SERVICES)
        run('sync')
        run('umount',str(MOUNT))
        if MOUNT.is_mount():
            raise SystemExit('Still mounted. Do not disconnect.')
        saved['unmounted'] = True
        STATE.write_text(json.dumps(saved,indent=2))
        print('SAFE TO DISCONNECT. Swap to a USB 3 data cable and blue USB 3 port.')
        print('After reconnecting, run: sudo python3 /home/hackrf/capture-station/swap_t7.py resume')
    else:
        saved = json.loads(STATE.read_text())
        if not saved.get('unmounted'):
            raise SystemExit('No completed safe unmount is recorded. Leave the SSD connected for inspection.')
        if not MOUNT.is_mount():
            run('mount',str(MOUNT))
        if (MOUNT/'.field-station-volume').read_text().strip()!='S6XBNS0W321351N':
            raise SystemExit('Wrong SSD mounted; services were not resumed.')
        run('systemctl','start',*saved['services'])
        config = ROOT/'run/automatic.json'
        tmp = config.with_suffix('.tmp')
        tmp.write_text(json.dumps(saved['automatic'],indent=2))
        os.chown(tmp, account.pw_uid, account.pw_gid)
        tmp.replace(config)
        if saved.get('rf_trigger'):
            trigger_config = ROOT/'run/rf-trigger.json'
            values = saved['rf_trigger']
            keys = ('enabled','threshold_db','confirm_snapshots','duration_minutes','cooldown_minutes','min_bandwidth_khz',
                    'hysteresis_db','quiet_snapshots','temporal_threshold_db','broadband_rise_db','baseline_samples',
                    'baseline_window','broadband_fraction','max_delay_seconds')
            restored={k:values[k] for k in keys if k in values}
            restored['last_fired_epoch']=max(0,values.get('cooldown_until_epoch',0)-values.get('cooldown_minutes',10)*60)
            trigger_config.write_text(json.dumps(restored,indent=2))
            os.chown(trigger_config,account.pw_uid,account.pw_gid)
        if saved.get('motion_trigger'):
            values = saved['motion_trigger']
            keys = ('enabled','duration_minutes','pre_roll_seconds','post_roll_seconds','cooldown_minutes','analysis_fps','analysis_width','pixel_threshold','min_area_percent',
                    'max_area_percent','confirmation_seconds','reference_seconds','roi_left','roi_top','roi_right','roi_bottom','roi_polygon')
            restored = {k:values[k] for k in keys if k in values}
            restored['last_fired_epoch'] = max(0,values.get('cooldown_until_epoch',0)-values['cooldown_minutes']*60)
            motion_config = ROOT/'run/motion-trigger.json'
            motion_config.write_text(json.dumps(restored,indent=2))
            os.chown(motion_config,account.pw_uid,account.pw_gid)
        run('runuser','-u','hackrf','--','env','XDG_RUNTIME_DIR=/run/user/1000',
            'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus','systemctl','--user','restart','capture-station.service')
        for _ in range(30):
            try:
                s = status()
                if s['rf']['fresh']:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        saved['unmounted'] = False
        STATE.write_text(json.dumps(saved,indent=2))
        run('lsusb','-t')
        print('SSD mounted; RF logging, SMB, and the saved automatic schedule have resumed.')

if __name__=='__main__':
    main()
