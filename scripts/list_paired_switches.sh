#!/bin/bash
# Lists paired Bluetooth devices for the default adapter, most-recent bond first.
# Useful for finding the address to pass to `run_controller_cli.py -r <addr>`.
#
# bluez stores per-device bond data under /var/lib/bluetooth/<adapter>/<addr>/info.
# The file's mtime is bumped on connect / link-key update / disconnect, so sorting
# by mtime gives a reasonable "most recently used" ordering. (Not exact connection
# timestamps — bluez doesn't keep those.)
#
# Requires root because /var/lib/bluetooth is mode 0700.

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "must be run as root" >&2
    exit 1
fi

ADAPTER=$(bluetoothctl show | awk '/Controller/{print $2; exit}')
if [ -z "$ADAPTER" ]; then
    echo "no Bluetooth adapter found" >&2
    exit 1
fi

DIR=/var/lib/bluetooth/$ADAPTER
if [ ! -d "$DIR" ]; then
    echo "no bond directory at $DIR" >&2
    exit 1
fi

found=0
for d in $(ls -1t "$DIR" 2>/dev/null | grep -E '^[0-9A-F:]{17}$'); do
    name=$(grep -m1 '^Name=' "$DIR/$d/info" 2>/dev/null | cut -d= -f2-)
    ts=$(stat -c %y "$DIR/$d/info" 2>/dev/null | cut -d. -f1)
    printf "%s  %-20s  %s\n" "$d" "${name:-(unknown)}" "$ts"
    found=1
done

if [ "$found" -eq 0 ]; then
    echo "no paired devices for adapter $ADAPTER"
fi
