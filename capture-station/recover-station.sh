#!/bin/sh
# Root-owned, narrowly scoped recovery of the existing recording volume/services.
set -eu
MOUNT=/home/hackrf/t7
UUID=a8ec8f1e-b658-4182-87b4-34b56cf70a5b
if ! mountpoint -q "$MOUNT"; then
    # Only attempt the configured mount when its exact UUID is present.
    test -e "/dev/disk/by-uuid/$UUID" || exit 0
    systemctl reset-failed home-hackrf-t7.mount || true
    systemctl start home-hackrf-t7.mount || exit 0
fi
[ "$(findmnt -n -o UUID --mountpoint "$MOUNT")" = "$UUID" ] || exit 0
[ "$(cat "$MOUNT/.field-station-volume")" = S6XBNS0W321351N ] || exit 0
for unit in openwebrx.service hackrf-signal-logger.service hackrf-signal-publish.timer smbd.service; do
    if ! systemctl is-active --quiet "$unit"; then
        systemctl reset-failed "$unit" || true
        systemctl start "$unit" || true
    fi
done
# A running receiver can stall after USB initialization; allow three minutes.
now=$(date +%s)
last=$(stat -c %Y "$MOUNT/signal-spool/live.json" 2>/dev/null || echo 0)
read -r uptime_seconds rest < /proc/uptime
if [ "${uptime_seconds%%.*}" -gt 180 ] && [ "$((now-last))" -gt 180 ]; then
    state=/run/field-station-recovery-last-rf-restart
    previous=$(cat "$state" 2>/dev/null || echo 0)
    if [ "$((now-previous))" -ge 180 ]; then
        printf '%s\n' "$now" > "$state"
        systemctl restart openwebrx.service hackrf-signal-logger.service
    fi
fi
