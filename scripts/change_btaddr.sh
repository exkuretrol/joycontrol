#!/bin/bash

# changes the vendor part (first 3 bytes) of the Mac address on a raspi 4B (tested)
# and 3B+ (untestd) to 94:58:CB for Nintendo Co. Ltd.

# For some reason after a reboot you have to run
# sudo btmgmt --index 0 public-addr 11:22:33:44:55:66
# (or, on systems still shipping bluez-tools' hcitool:
#  sudo hcitool cmd 0x3f 0x001 0x66 0x55 0x44 0x33 0x22 0x11 — note reversed byte order)

set -e

if [ -z "$1" ]; then
	bdaddr_dev=$(bluetoothctl show | grep -Eo '(:[0-9a-fA-F]{2}){3}\s')
	target_addr="94:58:CB${bdaddr_dev}"
	echo "detected dev id: ${bdaddr_dev}"
else
	target_addr=$1
fi

echo "changing address to ${target_addr}"

if command -v bdaddr >/dev/null 2>&1; then
	bdaddr -i hci0 "${target_addr}"
elif command -v btmgmt >/dev/null 2>&1; then
	btmgmt --index 0 public-addr "${target_addr}"
else
	echo "neither bdaddr nor btmgmt is installed; cannot change BD address" >&2
	exit 1
fi

# Reset the adapter. Modern: btmgmt power cycle. Fallback: deprecated hciconfig.
if command -v btmgmt >/dev/null 2>&1; then
	btmgmt --index 0 power off
	btmgmt --index 0 power on
elif command -v hciconfig >/dev/null 2>&1; then
	echo "btmgmt not found; falling back to deprecated hciconfig" >&2
	hciconfig hci0 reset
fi

systemctl restart bluetooth.service

echo "success"
