#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run this installer with sudo.'; exit 1; }
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -o root -g root -m 755 "$BASE/recover-station.sh" /usr/local/sbin/field-station-recovery
cat > /etc/systemd/system/field-station-recovery.service <<'UNIT'
[Unit]
Description=Recover field station SSD and logging services
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/field-station-recovery
TimeoutStartSec=90
UNIT
cat > /etc/systemd/system/field-station-recovery.timer <<'UNIT'
[Unit]
Description=Retry field station storage and services after boot

[Timer]
OnBootSec=45s
OnUnitInactiveSec=60s
Unit=field-station-recovery.service

[Install]
WantedBy=timers.target
UNIT
mkdir -p /etc/systemd/system/smbd.service.d
cat > /etc/systemd/system/smbd.service.d/recovery.conf <<'UNIT'
[Unit]
StartLimitIntervalSec=0

[Service]
Restart=on-failure
RestartSec=5
UNIT
loginctl enable-linger hackrf
systemctl daemon-reload
systemctl enable openwebrx.service hackrf-signal-logger.service hackrf-signal-publish.timer smbd.service
systemctl enable --now field-station-recovery.timer
systemctl start field-station-recovery.service
systemctl status field-station-recovery.timer --no-pager
