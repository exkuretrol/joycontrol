import asyncio
import logging
import os
import socket
import sys
import time
from importlib.resources import files

import dbus

from joycontrol import utils
from joycontrol.device import HidDevice
from joycontrol.report import InputReport
from joycontrol.transport import L2CAP_Transport

PROFILE_PATH = str(files('joycontrol').joinpath('profile/sdp_record_hid.xml'))
logger = logging.getLogger(__name__)


async def _send_empty_input_reports(transport):
    report = InputReport()
    for i in range(10):
        await transport.write(report)
        await asyncio.sleep(1)


def _bond_mtime(adapter_addr: str, path: str) -> float:
    addr = HidDevice.get_address_of_paired_path(path)
    info_path = f"/var/lib/bluetooth/{adapter_addr}/{addr}/info"
    try:
        return os.path.getmtime(info_path)
    except OSError:
        return 0.0


def _list_paired(hid: HidDevice, adapter_addr: str):
    """Return paired Switch DBus paths sorted by last-bond mtime, newest first."""
    return sorted(hid.get_paired_switches(),
                  key=lambda p: _bond_mtime(adapter_addr, p),
                  reverse=True)


def _print_menu(paths, adapter_addr: str) -> None:
    print("found the following paired switches, please choose one:")
    for i, p in enumerate(paths, start=1):
        mt = _bond_mtime(adapter_addr, p)
        ts = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt))
              if mt > 0 else "unknown")
        print(f" {i}: {p}  (last bond: {ts})")
    print(" n: pair a new Switch")
    print(" u: unpair a Switch")
    print(" 0: abort")


def _prompt_unpair(hid: HidDevice, paths) -> None:
    """Ask which entry to unpair, then remove its bond. Tolerant of bad input."""
    if not paths:
        return
    raw = input(f"unpair which? number 1 - {len(paths)} (Enter to cancel): ").strip()
    if not raw:
        return
    try:
        idx = int(raw)
    except ValueError:
        print(f"unrecognized choice {raw!r}, cancelled")
        return
    if not 1 <= idx <= len(paths):
        print(f"choice {idx} out of range, cancelled")
        return
    target = paths[idx - 1]
    addr = HidDevice.get_address_of_paired_path(target)
    confirm = input(f"remove bond for {addr}? y/N: ").strip().lower()
    if confirm not in ('y', 'yes'):
        print("cancelled")
        return
    try:
        hid.unpair_path(target)
        print(f"unpaired {addr}")
    except Exception as exc:
        print(f"failed to unpair {addr}: {exc}")


def _resolve_auto(hid: HidDevice, adapter_addr: str, interactive: bool):
    """
    Resolve `-r auto` to either a concrete BD address (reconnect path) or
    None (fall through to initial pairing). When interactive, present a
    menu so the user can pick a paired Switch, pair a new one, unpair an
    existing one, or abort.

    :returns BD address string for reconnect, or None for initial pairing.
    """
    paths = _list_paired(hid, adapter_addr)
    if not paths:
        logger.info('no paired Switch found; falling back to initial pairing flow')
        return None

    if not interactive:
        if len(paths) > 1:
            logger.warning(f"Automatic reconnect address chose {paths[0]} out of {paths}")
        else:
            logger.info(f"auto detected paired switch {paths[0]}")
        return HidDevice.get_address_of_paired_path(paths[0])

    while True:
        if not paths:
            logger.info('no paired Switch left; falling back to initial pairing flow')
            return None

        _print_menu(paths, adapter_addr)
        choice = input(f"number 1 - {len(paths)}, n to pair new, u to unpair, 0 to abort [1]: ").strip().lower()

        if choice == '':
            return HidDevice.get_address_of_paired_path(paths[0])
        if choice in ('0', 'q'):
            print("aborted")
            sys.exit(0)
        if choice in ('n', 'new'):
            logger.info('user chose to pair a new Switch; falling through to initial pairing flow')
            return None
        if choice in ('u', 'unpair'):
            _prompt_unpair(hid, paths)
            paths = _list_paired(hid, adapter_addr)
            continue
        try:
            idx = int(choice)
        except ValueError:
            print(f"unrecognized choice {choice!r}, try again")
            continue
        if not 1 <= idx <= len(paths):
            print(f"choice {idx} out of range, try again")
            continue
        return HidDevice.get_address_of_paired_path(paths[idx - 1])

async def create_hid_server(protocol_factory, ctl_psm=17, itr_psm=19, device_id=None, reconnect_bt_addr=None,
                            capture_file=None, interactive=False):
    """
    :param protocol_factory: Factory function returning a ControllerProtocol instance
    :param ctl_psm: hid control channel port
    :param itr_psm: hid interrupt channel port
    :param device_id: ID of the bluetooth adapter.
                      Integer matching the digit in the hci* notation (e.g. hci0, hci1, ...) or
                      Bluetooth mac address in string notation of the adapter (e.g. "FF:FF:FF:FF:FF:FF").
                      If None, choose any device.
                      Note: Selection of adapters may currently not work if the bluez "input" plugin is enabled.
    :param reconnect_bt_addr: The Bluetooth address of the console that was previously connected. Defaults to None.
                      If None, a new hid server will be started for the initial paring.
                      Otherwise, the function assumes an initial pairing with the console was already done
                      and reconnects to the provided Bluetooth address.
    :param capture_file: opened file to log incoming and outgoing messages
    :param interactive: whether or not questions to the user via input and print are allowed
    :returns transport for input reports and protocol which handles incoming output reports
    """
    protocol = protocol_factory()

    hid = HidDevice(device_id=device_id)

    bt_addr = hid.get_address()
    #if bt_addr[:8] != "94:58:CB":
    #    await hid.set_address("94:58:CB" + bt_addr[8:], interactive=interactive)
    #    bt_addr = hid.get_address()

    # Normalize reconnect_bt_addr. The CLI default is 'auto', so the most
    # common case is "reconnect if a Switch is paired, otherwise fall through
    # to initial-pairing flow". Treat an empty string or 'none' as an explicit
    # opt-out from reconnect.
    if isinstance(reconnect_bt_addr, str):
        normalized = reconnect_bt_addr.strip().lower()
        if normalized in ('', 'none'):
            reconnect_bt_addr = None
        elif normalized == 'auto':
            reconnect_bt_addr = _resolve_auto(hid, bt_addr, interactive)

    if reconnect_bt_addr is None:
        # The user has already made the connect-vs-pair choice (either via
        # `-r <addr>` / `-r auto` picker, or by passing `-r none`). Don't
        # prompt to unpair existing bonds — pairing a new Switch should not
        # disturb other Switches the host is already bonded to.
        if interactive:
            if len(hid.get_UUIDs()) > 3:
                print("too many SDP records active, Switch might refuse connection.")
                print("try modifying /lib/systemd/system/bluetooth.service and see")
                print("https://github.com/Poohl/joycontrol/issues/4 if it doesn't work")
        else:
            if len(hid.get_UUIDs()) > 3:
                logger.warning("detected too many SDP records. Switch might refuse connection.")

        ctl_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        itr_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        ctl_sock.setblocking(False)
        itr_sock.setblocking(False)
        ctl_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        itr_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            ctl_sock.bind((bt_addr, ctl_psm))
            itr_sock.bind((bt_addr, itr_psm))
        except OSError as err:
            logger.warning(err)
            # If the ports are already taken, this probably means that the bluez "input" plugin is enabled.
            logger.warning('Fallback: Restarting bluetooth due to incompatibilities with the bluez "input" plugin. '
                           'Disable the plugin to avoid issues. See https://github.com/mart1nro/joycontrol/issues/8.')
            # HACK: To circumvent incompatibilities with the bluetooth "input" plugin, we need to restart Bluetooth here.
            # The Switch does not connect to the sockets if we don't.
            # For more info see: https://github.com/mart1nro/joycontrol/issues/8
            logger.info('Restarting bluetooth service...')
            await utils.run_system_command('systemctl restart bluetooth.service')
            await asyncio.sleep(1)
            hid = HidDevice(device_id=device_id)

            ctl_sock.bind((bt_addr, ctl_psm))
            itr_sock.bind((bt_addr, itr_psm))

        ctl_sock.listen(1)
        itr_sock.listen(1)

        hid.powered(True)
        hid.pairable(True)

        # setting bluetooth adapter name to the device we wish to emulate
        await hid.set_name(protocol.controller.device_name())

        logger.info('Advertising the Bluetooth SDP record...')
        try:
            HidDevice.register_sdp_record(PROFILE_PATH)
        except dbus.exceptions.DBusException as dbus_err:
            # Already registered (If multiple controllers are being emulated and this method is called consecutive times)
            logger.debug(dbus_err)

        # start advertising
        hid.discoverable()

        # set the device class to "Gamepad/joystick"
        await hid.set_class()

        logger.info('Waiting for Switch to connect... Please open the "Change Grip/Order" menu.')

        loop = asyncio.get_running_loop()
        client_ctl, ctl_address = await loop.sock_accept(ctl_sock)
        logger.info(f'Accepted connection at psm {ctl_psm} from {ctl_address}')
        client_itr, itr_address = await loop.sock_accept(itr_sock)
        logger.info(f'Accepted connection at psm {itr_psm} from {itr_address}')
        assert ctl_address[0] == itr_address[0]

        # stop advertising
        hid.discoverable(False)
        hid.pairable(False)

    else:
        # reconnect_bt_addr is already a concrete address — _resolve_auto
        # handled the 'auto' case earlier and either returned an address
        # or None (which would have hit the if-None branch above).
        # Reconnection to reconnect_bt_addr
        client_ctl = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        client_itr = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        client_ctl.connect((reconnect_bt_addr, ctl_psm))
        client_itr.connect((reconnect_bt_addr, itr_psm))
        client_ctl.setblocking(False)
        client_itr.setblocking(False)

    # I have spent 8 hours, one stackoverflow question and read pythons socket sourcecode
    # to find tis fucking option somewhere in a GNUC API description. (here: https://www.gnu.org/software/libc/manual/html_node/Socket_002dLevel-Options.html)
    # FUCK LINUX OPEN SOURCE. I'd rather have a DOCUMENTATION than the source of this garbage.
    client_ctl.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
    client_itr.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
    # create transport for the established connection and activate the HID protocol
    transport = L2CAP_Transport(asyncio.get_running_loop(), protocol, client_itr, client_ctl, 50, capture_file=capture_file)
    protocol.connection_made(transport)

    # HACK: send some empty input reports until the Switch decides to reply
    future = asyncio.ensure_future(_send_empty_input_reports(transport))
    await protocol.wait_for_output_report()
    """
    future.cancel()
    try:
        await future
    except asyncio.CancelledError:
        pass
    """

    return protocol.transport, protocol
