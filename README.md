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
Linux 10.1 with Python 3.12 / BlueZ 5.83). The legacy `hciconfig` /
`hcitool` tools are deprecated on modern distributions; this project
prefers `btmgmt` (the modern bluez management tool) and falls back to
the legacy tools only when present.

These steps assume a fresh setup. Run them in order. Everything below
is reversible — nothing is installed system-wide except a few distro
packages and a systemd drop-in (covered in *Bluetooth service setup*
below).

### Step 1 — Get the source

```bash
git clone https://github.com/Poohl/joycontrol.git
cd joycontrol
```

(Substitute your own fork URL if you're using one.)

### Step 2 — Install the system packages

joycontrol talks to BlueZ over D-Bus and reads HID devices via HIDAPI,
so a few distro packages have to be present. This step is the only one
that needs to touch system state outside the project directory.

**Debian / Ubuntu / Raspberry Pi OS (Raspbian):**

```bash
sudo apt update
sudo apt install python3-venv python3-dbus libhidapi-hidraw0 libbluetooth-dev bluez bluez-tools
```

**Fedora / RHEL / Oracle Linux 10:**

`bluez-libs-devel` lives in the **CodeReady Builder** repo, which is
disabled by default — enable it once with the line that matches your
distro:

```bash
# Oracle Linux 10
sudo dnf config-manager --enable ol10_codeready_builder

# AlmaLinux / Rocky Linux 10
sudo dnf config-manager --set-enabled crb

# Red Hat Enterprise Linux 10 (with an active subscription)
sudo subscription-manager repos --enable codeready-builder-for-rhel-10-x86_64-rpms
```

Then install the packages:

```bash
sudo dnf install python3 python3-dbus hidapi bluez bluez-libs-devel
```

> **Why no `bluez-tools`?** On Debian-family distros, `btmgmt` ships in
> a separate `bluez-tools` package; on RHEL-family distros it lives
> *inside* the main `bluez` package. Either way, you end up with
> `btmgmt` available — that's what joycontrol uses.

### Step 3 — Create a Python virtualenv

A virtualenv keeps the project's Python dependencies isolated from
the rest of your system so they don't conflict with anything else.

From the cloned project directory, run:

```bash
python3 -m venv --system-site-packages .venv
```

This creates a `.venv/` folder inside the project. The
`--system-site-packages` flag is **important**: it lets the venv see
the distro-installed `python3-dbus` from step 2.

> **Why `--system-site-packages`?** `python3-dbus` is a C extension
> that links against your system's D-Bus libraries. Building it from
> source via `pip` requires a C toolchain plus dbus/glib headers, and
> usually fails. Having the venv inherit the distro package
> sidesteps that whole problem.

### Step 4 — Install joycontrol

This installs the joycontrol package and its remaining Python
dependencies (`hid`, `crc8`, `prompt-toolkit`) *into* the venv:

```bash
sudo .venv/bin/pip install .
```

`sudo` is needed here only because the next step (running joycontrol)
must be root to access raw Bluetooth sockets, and the venv files
should be readable by root.

### Step 5 — Verify the install

```bash
sudo .venv/bin/python -c "import dbus, hid, crc8, prompt_toolkit"
```

Should print nothing and exit cleanly. If you get
`ModuleNotFoundError: No module named 'dbus'`, you forgot
`--system-site-packages` in step 3 — delete `.venv/` and redo step 3.

---

After these five steps the Python side is done. You **also** need to
adjust BlueZ so the Switch will accept connections — that's the next
section. Without that, the script will start but the Switch will
reject the controller during pairing.

## Bluetooth service setup

The Switch is picky about what it connects to. If the host advertises
extra Bluetooth profiles (audio remote, SIM access, regular HID
input), the Switch sees too many service records and **refuses to
pair**. We tell BlueZ to drop those plugins so the controller is the
only thing the Switch sees.

The cleanest way is a **systemd drop-in override** — a small
configuration file that adjusts the existing `bluetooth.service`
without touching anything BlueZ ships, so it survives package updates.

### Step 1 — Find your bluetoothd binary path

```bash
systemctl cat bluetooth.service | grep -m1 ExecStart=/usr
```

You'll see one of these two paths in the output:

| Distro family                | `bluetoothd` path                       |
|------------------------------|-----------------------------------------|
| Fedora / RHEL / Oracle Linux | `/usr/libexec/bluetooth/bluetoothd`     |
| Debian / Ubuntu / Raspbian   | `/usr/lib/bluetooth/bluetoothd`         |

Note which one you have — you'll plug it into the next step.

### Step 2 — Write the override

Replace `/usr/libexec/bluetooth/bluetoothd` below with the path you
found in step 1 if yours differs:

```bash
sudo mkdir -p /etc/systemd/system/bluetooth.service.d
sudo tee /etc/systemd/system/bluetooth.service.d/override.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/libexec/bluetooth/bluetoothd -C -P sap,input,avrcp
EOF
```

The blank `ExecStart=` line is important — it tells systemd to discard
BlueZ's default command before applying ours.

### Step 3 — Reload and restart bluetoothd

```bash
sudo systemctl daemon-reload
sudo systemctl restart bluetooth.service
```

### Step 4 — Verify

```bash
ps -ef | grep bluetoothd | grep -v grep
```

You should see the daemon running with the `-C -P sap,input,avrcp`
flags appended, e.g.:

```
root  7274  ... /usr/libexec/bluetooth/bluetoothd -C -P sap,input,avrcp
```

Confirm there's a working adapter too (especially if you're inside a
VM — the host might have Bluetooth, but the VM might not):

```bash
bluetoothctl show
```

You want a `Controller` line with a real BD address (e.g. `5C:F3:70:…`).
If you don't, joycontrol won't be able to do anything until you fix
the adapter situation — typically by passing through a USB Bluetooth
dongle or running on bare metal.

### What this breaks (host-wide)

The override disables three BlueZ plugins for *everything* on this
machine, not just joycontrol. After applying it:

- `input` — Bluetooth keyboards / mice / game controllers won't work.
- `sap`   — SIM Access Profile (used to share a phone's SIM with a
  car kit) won't work; almost certainly nobody cares.
- `avrcp` — media remote control over Bluetooth (play/pause from BT
  headphones, etc.) won't work.

For *reconnecting* to a Switch you've already paired with, you can
sometimes get away with disabling only `input`. But **initial pairing
needs all three** disabled or the Switch refuses the connection. See
[Issue #4](https://github.com/Poohl/joycontrol/issues/4) for the
underlying details.

To revert: delete `/etc/systemd/system/bluetooth.service.d/override.conf`
and restart bluetooth.service.

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
