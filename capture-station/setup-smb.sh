#!/bin/bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo 'Run with sudo in the Pi terminal; setup needs administrator access.' >&2
    exit 1
fi

station_root=/home/hackrf/capture-station
if ! mountpoint -q /home/hackrf/t7; then
    echo 'Samsung T7 is not mounted. No SMB settings changed.' >&2
    exit 1
fi
if [ "$(cat /home/hackrf/t7/.field-station-volume)" != S6XBNS0W321351N ]; then
    echo 'Unexpected storage volume. No SMB settings changed.' >&2
    exit 1
fi

apt-get install -y --no-install-recommends samba smbclient
testparm -s "$station_root/smb.conf"
if [ -f /etc/samba/smb.conf ]; then
    cp -a /etc/samba/smb.conf "/etc/samba/smb.conf.field-station-backup-$(date +%s)"
fi
install -m 644 "$station_root/smb.conf" /etc/samba/smb.conf
chown hackrf:hackrf /home/hackrf/t7
install -d -o hackrf -g hackrf -m 0770 /home/hackrf/t7/Uploads
mkdir -p /etc/systemd/system/smbd.service.d
cat > /etc/systemd/system/smbd.service.d/t7-storage.conf <<'UNIT'
[Unit]
RequiresMountsFor=/home/hackrf/t7
ConditionPathIsMountPoint=/home/hackrf/t7
UNIT

if ! pdbedit -L -u hackrf 2>/dev/null | rg -q '^hackrf:'; then
    echo 'Choose an SMB password for username hackrf. Enter it twice when prompted.'
    smbpasswd -a hackrf
fi
smbpasswd -e hackrf
systemctl daemon-reload
systemctl disable --now nmbd.service
systemctl enable --now smbd.service
systemctl restart smbd.service
systemctl is-active smbd.service
echo
echo 'SMB is ready. The T7 share is password-protected and writable by hackrf.'
echo 'iPad Files > Browse > ... > Connect to Server'
echo 'LAN: smb://192.168.8.208'
echo 'Tailscale: smb://100.117.92.45'
echo 'Choose Registered User; username: hackrf; password: the SMB password you set.'
