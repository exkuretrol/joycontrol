# joycontrol

Branch: master->amiibo_edits

Emulate Nintendo Switch Controllers over Bluetooth.

Tested on Raspberry 4B Raspbian, should work on 3B+ too and anything that can do the setup.

## Features
Emulation of JOYCON_R, JOYCON_L and PRO_CONTROLLER. Able to send:
- button commands
- stick state
- nfc for amiibo read & owner registration

## Installation

Tested on Python 3.9+ and BlueZ 5.55+ (verified on Raspbian and Oracle
Linux 10 with Python 3.12 / BlueZ 5.83). The legacy `hciconfig` /
`hcitool` tools are deprecated on modern distributions; this project
prefers `btmgmt` (part of `bluez-tools`) and falls back to the legacy
tools only when present.

### System packages

Debian / Ubuntu / Raspbian:
```bash
sudo apt install python3-dbus libhidapi-hidraw0 libbluetooth-dev bluez bluez-tools
```

Fedora / RHEL / Oracle Linux:
```bash
sudo dnf install python3-dbus hidapi bluez bluez-libs-devel bluez-tools
```

`bluez-libs-devel` lives in the CodeReady Builder repo, which is not
enabled by default. Enable it first if `dnf` can't find the package:

```bash
# Oracle Linux 10
sudo dnf config-manager --enable ol10_codeready_builder

# RHEL 10 (with a Red Hat subscription)
sudo subscription-manager repos --enable codeready-builder-for-rhel-10-x86_64-rpms

# AlmaLinux / Rocky Linux 10
sudo dnf config-manager --set-enabled crb
```

Adjust the version number (`ol10_…`, `…rhel-10-…`) for your release.

`bluez-tools` provides `btmgmt`, which is the modern replacement for
`hciconfig` / `hcitool` and is now the default path used by joycontrol.

### Python packages

Easiest — install the project (which pulls in all Python deps) directly:

```bash
sudo pip3 install .
```

A project-local venv is fine too:

```bash
python3 -m venv .venv
sudo .venv/bin/pip install .
```

joycontrol must run as root (raw L2CAP sockets), so install where the
root user can find the packages — either system-wide or in a venv that
you'll launch via `sudo .venv/bin/python ...`.

To verify the install:
```bash
sudo python3 -c "import dbus, hid, aioconsole, crc8, prompt_toolkit"
```
Should exit silently.

## Bluetooth service setup

The Switch refuses to connect if the adapter advertises non-controller
profiles like AVRCP — you need to disable the `input`, `sap`, and
`avrcp` plugins on `bluetoothd`. The maintainable way is a systemd
drop-in (won't be clobbered by package upgrades):

```bash
sudo mkdir -p /etc/systemd/system/bluetooth.service.d
sudo tee /etc/systemd/system/bluetooth.service.d/override.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/libexec/bluetooth/bluetoothd -C -P sap,input,avrcp
EOF
sudo systemctl daemon-reload
sudo systemctl restart bluetooth.service
```

The `bluetoothd` binary path differs by distro:
- `/usr/libexec/bluetooth/bluetoothd` — Fedora / RHEL family
- `/usr/lib/bluetooth/bluetoothd`     — Debian / Ubuntu / Raspbian

Check yours and adjust the override if needed:
```bash
systemctl cat bluetooth.service | grep -m1 ExecStart=/usr
```

Verify the right flags are in effect:
```bash
ps -ef | grep bluetoothd
# ... /usr/libexec/bluetooth/bluetoothd -C -P sap,input,avrcp
```

### What this breaks (host-wide)
- `input` — disables Bluetooth keyboards / mice / joysticks on this host.
- `sap`   — SIM Access Profile (rarely used).
- `avrcp` — media remote control (e.g. play/pause from BT headphones).

For *reconnecting* to an already-paired Switch you can sometimes get
away with only disabling `input`, but **initial pairing** needs all
three or the Switch sees too many SDP records and refuses (see
[Issue #4](https://github.com/Poohl/joycontrol/issues/4)).

### Make sure the adapter actually exists

If running in a VM, the host might have Bluetooth but the VM might
not. Confirm with `bluetoothctl show` — you want to see a `Controller`
line with a real BD address.

## Command line interface example

A simple CLI lives in `run_controller_cli.py`. Bare invocation:

```bash
sudo python3 run_controller_cli.py
```

…defaults to emulating a Pro Controller and reconnecting to your most
recently paired Switch (or falling through to initial pairing if none).

Startup options:

```
usage: run_controller_cli.py [-h] [-l LOG] [-d DEVICE_ID]
                             [--spi_flash SPI_FLASH] [-r RECONNECT_BT_ADDR]
                             [--nfc NFC]
                             [{JOYCON_L,JOYCON_R,PRO_CONTROLLER}]

positional arguments:
  {JOYCON_L,JOYCON_R,PRO_CONTROLLER}
                        controller type to emulate (default: PRO_CONTROLLER)

options:
  -h, --help            show this help message and exit
  -l LOG, --log LOG     BT-communication logfile output
  -d DEVICE_ID, --device_id DEVICE_ID
                        not fully working yet, the BT-adapter to use
  --spi_flash SPI_FLASH
                        controller SPI-memory dump to use
  -r RECONNECT_BT_ADDR, --reconnect_bt_addr RECONNECT_BT_ADDR
                        Switch BD address, "auto" (the default) for picker,
                        or "" / "none" to force initial pairing
  --nfc NFC             amiibo dump placed on the controller (same as the
                        in-prompt `nfc` command)
```

### Pairing / reconnecting

When at least one Switch is already paired, the script presents an
interactive picker:

```
found the following paired switches, please choose one:
 1: /org/bluez/hci0/dev_AA_AA_AA_AA_AA_AA  (last bond: 2026-05-01 16:36:48)
 2: /org/bluez/hci0/dev_BB_BB_BB_BB_BB_BB  (last bond: 2026-05-01 14:31:04)
 n: pair a new Switch
 u: unpair a Switch
 0: abort
number 1 - 2, n to pair new, u to unpair, 0 to abort [1]:
```

| Input          | Result                                                               |
|----------------|----------------------------------------------------------------------|
| Enter          | reconnect to the most-recently bonded Switch (option 1)              |
| `1`–`N`        | reconnect to that entry                                              |
| `n` / `new`    | initial-pairing flow — open *Change Grip/Order* on the Switch        |
| `u` / `unpair` | pick a Switch to forget (with `y/N` confirm), menu reflows           |
| `0` / `q`      | exit cleanly                                                         |

To bypass the picker entirely:
- `-r 04:03:D6:8F:08:B5` — reconnect to that specific BD address
- `-r ""` or `-r none`   — force initial pairing even if other Switches are paired

If no Switch is paired yet, the picker is skipped and the script goes
straight to the initial-pairing flow — open *Change Grip/Order* on the
Switch.

### Inspecting paired Switches

`scripts/list_paired_switches.sh` lists paired devices for the default
adapter, sorted by last-bond timestamp:

```bash
sudo ./scripts/list_paired_switches.sh
# 04:03:D6:8F:08:B5  Nintendo Switch       2026-05-01 16:36:48
```

### Inside the prompt

Once connected, a `cmd >>` prompt opens with:

- **Tab** — completes commands and button names.
- **↑ / ↓** — recalls previous commands (persisted at
  `~/.local/state/joycontrol/cli_history`, overridable via
  `$JOYCONTROL_STATE_DIR` or `$XDG_STATE_HOME`).
- Logs render *above* the prompt without disturbing your input.
- **Ctrl-D** / **Ctrl-C** / `exit` exit cleanly.

Type `help` for the full command list (button names, `stick`, `mash`,
`hold`/`release`, `nfc`, `pause`/`unpause`, etc.).

## API

See the `run_controller_cli.py` for an example how to use the API. A minimal example:

```python
from joycontrol.protocol import controller_protocol_factory
from joycontrol.server import create_hid_server
from joycontrol.controller import Controller

# the type of controller to create
controller = Controller.PRO_CONTROLLER # or JOYCON_L or JOYCON_R
# a callback to create the corresponding protocol once a connection is established
factory = controller_protocol_factory(controller)
# start the emulated controller
transport, protocol = await create_hid_server(factory)
# get a reference to the state beeing emulated.
controller_state = protocol.get_controller_state()
# wait for input to be accepted
await controller_state.connect()
# some sample input
controller_state.button_state.set_button('a', True)
# wait for it to be sent at least once
await controller_state.send()
```

## Issues
- Some Bluetooth adapters cause disconnects for reasons unknown — try a USB adapter or a Raspberry Pi instead.
- Incompatibility with Bluetooth "input" plugin (and `sap` / `avrcp` for initial pairing) requires them to be disabled — see the *Bluetooth service setup* section above and [Issue #8](https://github.com/mart1nro/joycontrol/issues/8).
- Reconnect spins (`bluetoothctl` shows the connection bouncing on/off) usually means the Switch lost its bond key but the host still has one. Use the `u` / unpair option in the picker to forget the host's bond, then pick `n` to pair fresh.
- ...

## Thanks
- Special thanks to https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering for reverse engineering of the joycon protocol
- Thanks to the growing number of contributers and users

## Resources

[Nintendo_Switch_Reverse_Engineering](https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering)

[console_pairing_session](https://github.com/timmeh87/switchnotes/blob/master/console_pairing_session)

[Hardware Issues thread](https://github.com/Poohl/joycontrol/issues/4)
