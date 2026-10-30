#!/usr/bin/env python3
"""Provision only the explicitly authorized Samsung T7; run with sudo."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

SERIAL = 'S6XBNS0W321351N'
DISK = Path('/dev/disk/by-id/usb-Samsung_PSSD_T7_' + SERIAL + '-0:0')
PART = Path(str(DISK) + '-part1')
MOUNT = Path('/home/hackrf/t7')
ROOT = Path('/home/hackrf/capture-station')
MARKER = MOUNT / '.field-station-volume'

def run(*args, capture=False):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout

def user_systemctl(*args):
    return run('runuser', '-u', 'hackrf', '--', 'env', 'XDG_RUNTIME_DIR=/run/user/1000',
               'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus', 'systemctl', '--user', *args)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.digest()

def migrate(source, destination, uid, gid):
    if source.is_symlink():
        if source.resolve() != destination.resolve():
            raise RuntimeError(f'Unexpected existing symlink: {source}')
        return
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)
        for p in source.rglob('*'):
            if p.is_file() and sha(p) != sha(destination / p.relative_to(source)):
                raise RuntimeError(f'Copy verification failed: {p}')
        backup = source.with_name(source.name + '.sd-backup-' + str(time.time_ns()))
        source.rename(backup)
        print(f'Original data preserved at {backup}', flush=True)
    else:
        destination.mkdir(parents=True, exist_ok=True)
    for p in [destination, *destination.rglob('*')]:
        os.chown(p, uid, gid)
    source.symlink_to(destination, target_is_directory=True)
    os.lchown(source, uid, gid)

def main():
    if sys.argv[1:] != ['--erase-' + SERIAL]:
        raise SystemExit('Use --erase-' + SERIAL + ' to erase ONLY this 1 TB Samsung T7.')
    if os.geteuid() != 0:
        raise SystemExit('Administrator access required. Run this command with sudo in the Pi terminal.')
    info = json.loads(run('lsblk', '--json', '-b', '-o', 'PATH,MODEL,SERIAL,SIZE,TYPE,MOUNTPOINTS', DISK, capture=True))['blockdevices'][0]
    if info['serial'] != SERIAL or info['type'] != 'disk' or not 990_000_000_000 < int(info['size']) < 1_010_000_000_000:
        raise RuntimeError('Drive identity/size mismatch; refusing to erase anything.')
    if not MOUNT.is_mount() and PART.exists():
        fs = subprocess.run(['blkid', '-s', 'TYPE', '-o', 'value', str(PART)], capture_output=True, text=True).stdout.strip()
        if fs == 'ext4':
            # Resume a prior setup without ever formatting its recordings again.
            MOUNT.mkdir(exist_ok=True)
            os.chown(MOUNT, 0, 0)
            MOUNT.chmod(0o555)
            run('mount', PART, MOUNT)
            if not MARKER.exists() or MARKER.read_text().strip() != SERIAL:
                run('umount', MOUNT)
                raise RuntimeError('Existing ext4 volume lacks the station marker; refusing to erase it.')
    mounted = MOUNT.is_mount()
    ours = mounted and MARKER.exists() and MARKER.read_text().strip() == SERIAL
    if mounted and not ours:
        raise RuntimeError('Mount path already contains another drive; refusing to proceed.')
    if not ours and any(any(p for p in c.get('mountpoints', []) if p) for c in [info, *info.get('children', [])]):
        raise RuntimeError('T7 has a mounted partition. Unmount it before setup.')
    try:
        with urlopen('http://127.0.0.1:8090/api/status', timeout=5) as response:
            if json.load(response)['active']:
                raise RuntimeError('A session is recording. Stop it before setup.')
    except OSError:
        pass
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'hackrf-signal-publish.service']).returncode == 0:
        raise RuntimeError('RF publisher is busy. Rerun setup after its current upload completes.')
    account = pwd.getpwnam('hackrf')
    uid, gid = account.pw_uid, account.pw_gid
    restart_needed = False
    try:
        user_systemctl('stop', 'capture-station.service')
        restart_needed = True
        if not ours:
            print(f'Formatting authorized T7 {SERIAL}. The Pi SD card is excluded.', flush=True)
            run('parted', '--script', '--align', 'optimal', DISK, 'mklabel', 'gpt', 'mkpart', 'primary', 'ext4', '1MiB', '100%')
            run('udevadm', 'settle')
            for _ in range(30):
                if PART.exists():
                    break
                time.sleep(0.2)
            run('mkfs.ext4', '-F', '-L', 'FIELD_STATION', PART)
            MOUNT.mkdir(exist_ok=True)
            # An absent drive must not turn this mount path into SD-card storage.
            os.chown(MOUNT, 0, 0)
            MOUNT.chmod(0o555)
            run('mount', PART, MOUNT)
            MARKER.write_text(SERIAL + '\n')
            MARKER.chmod(0o444)
        actual = run('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', MOUNT, capture=True).strip()
        if Path(actual).resolve() != PART.resolve():
            raise RuntimeError('Mounted device does not match the authorized T7 partition.')
        uuid = run('blkid', '-s', 'UUID', '-o', 'value', PART, capture=True).strip()
        if not uuid:
            raise RuntimeError('No filesystem UUID returned')
        fstab = Path('/etc/fstab')
        original = fstab.read_text()
        lines = original.splitlines()
        for line in lines:
            fields = line.split()
            if len(fields) >= 2 and not line.lstrip().startswith('#') and fields[1] == str(MOUNT) and fields[0] != 'UUID=' + uuid:
                raise RuntimeError('Another fstab entry uses the T7 mount path')
        if not any(line.split()[:2] == ['UUID='+uuid, str(MOUNT)] for line in lines):
            shutil.copy2(fstab, '/etc/fstab.field-station-backup-' + str(time.time_ns()))
            with fstab.open('a') as stream:
                stream.write(f'\nUUID={uuid} {MOUNT} ext4 defaults,noatime,nofail,x-systemd.device-timeout=10s 0 2\n')
        for name in ('sessions', 'signal-spool'):
            folder = MOUNT / name
            folder.mkdir(exist_ok=True, mode=0o700)
            os.chown(folder, uid, gid)
        run('systemctl', 'stop', 'hackrf-signal-publish.timer')
        # Catch an upload that started during formatting before moving its files.
        while subprocess.run(['systemctl', 'is-active', '--quiet', 'hackrf-signal-publish.service']).returncode == 0:
            print('Waiting for the in-flight RF publisher...', flush=True)
            time.sleep(2)
        run('systemctl', 'stop', 'hackrf-signal-logger.service')
        migrate(ROOT / 'sessions', MOUNT / 'sessions', uid, gid)
        migrate(Path('/home/hackrf/signal-spool'), MOUNT / 'signal-spool', uid, gid)
        for service in ('hackrf-signal-logger.service', 'hackrf-signal-publish.service'):
            dropin = Path('/etc/systemd/system') / (service + '.d')
            dropin.mkdir(exist_ok=True)
            (dropin / 't7-storage.conf').write_text(f'[Unit]\nRequiresMountsFor={MOUNT}\nConditionPathIsMountPoint={MOUNT}\n')
        dropin = Path('/home/hackrf/.config/systemd/user/capture-station.service.d')
        dropin.mkdir(exist_ok=True)
        os.chown(dropin, uid, gid)
        conf = dropin / 'storage.conf'
        conf.write_text(f'[Service]\nEnvironment=CAPTURE_DATA={MOUNT}/sessions\nEnvironment=CAPTURE_VOLUME={MOUNT}\nEnvironment=CAPTURE_VOLUME_ID={SERIAL}\n')
        os.chown(conf, uid, gid)
        run('systemctl', 'daemon-reload')
        user_systemctl('daemon-reload')
        run('findmnt', '--verify', '--verbose')
    finally:
        if restart_needed:
            run('systemctl', 'daemon-reload')
            run('systemctl', 'start', 'hackrf-signal-logger.service', 'hackrf-signal-publish.timer')
            user_systemctl('start', 'capture-station.service')
    run('df', '-h', MOUNT)
    print('T7 ready. Session recordings and the RF spool now use the SSD. Original SD copies were retained.', flush=True)

if __name__ == '__main__':
    main()
