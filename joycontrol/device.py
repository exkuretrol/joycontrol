import logging
import shutil
import uuid
import dbus

from joycontrol import utils

logger = logging.getLogger(__name__)


HID_UUID = '00001124-0000-1000-8000-00805f9b34fb'
HID_PATH = '/bluez/switch/hid'


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


class HidDevice:
    def __init__(self, device_id=None):
        self._device_id = device_id
        bus = dbus.SystemBus()
        # Get Bluetooth adapter from dbus interface
        for path, ifaces in bus.get_object('org.bluez', '/').GetManagedObjects(dbus_interface='org.freedesktop.DBus.ObjectManager').items():
            adapter_info = ifaces.get('org.bluez.Adapter1')
            if adapter_info and (device_id is None or device_id == adapter_info['Address'] or path.endswith(str(device_id))):
                self.dev = bus.get_object('org.bluez', path)
                break
        else:
            raise ValueError(f'Adapter {device_id} not found.')

        self.adapter = dbus.Interface(self.dev, 'org.bluez.Adapter1')
        # The sad news is someone decided that this convoluted mess passing
        # strings back and forth to get properties would be simpler than literal
        # adapter.some_property = 4 or adapter.some_property_set(4)
        self.properties = dbus.Interface(self.dev, 'org.freedesktop.DBus.Properties')
        self._adapter_name = self.dev.object_path.split("/")[-1]

    def get_address(self) -> str:
        """
        :returns adapter Bluetooth address
        """
        return str(self.properties.Get(self.adapter.dbus_interface, "Address"))

    async def set_address(self, bt_addr, interactive=True):
        if not interactive:
            return False
        # TODO: automated detection
        print(f"Attempting to change the bluetooth MAC to {bt_addr}")
        print("please choose your method:")
        print("\t1: bdaddr - ericson, csr, TI, broadcom, zeevo, st")
        print("\t2: btmgmt public-addr - intel chipsets / modern drivers")
        print("\t3: hcitool/raw HCI - cypress (raspberry pi 3B+ & 4B)")
        print("\tx: abort, don't change")
        hci_version = " ".join(reversed(list(map(lambda h: '0x' + h, bt_addr.split(":")))))
        adapter_idx = self._adapter_name.replace('hci', '')
        c = input()
        if c == '1':
            if not _has_cmd('bdaddr'):
                logger.error("bdaddr utility not found. Install it from your distro's bluez-tools or build from source.")
                return False
            await utils.run_system_command(f'bdaddr -i {self._adapter_name} {bt_addr}')
        elif c == '2':
            # Modern: btmgmt public-addr replaces the vendor HCI command for Intel chipsets
            if _has_cmd('btmgmt'):
                await utils.run_system_command(f'btmgmt --index {adapter_idx} public-addr {bt_addr}')
            elif _has_cmd('hcitool'):
                logger.warning('btmgmt not found, falling back to deprecated hcitool')
                await utils.run_system_command(f'hcitool cmd 0x3f 0x0031 {hci_version}')
            else:
                logger.error('Neither btmgmt nor hcitool is available')
                return False
        elif c == '3':
            # Cypress vendor command 0xfc01 — no btmgmt equivalent. Try hcitool, else raw HCI socket.
            if _has_cmd('hcitool'):
                await utils.run_system_command(f'hcitool cmd 0x3f 0x001 {hci_version}')
            else:
                logger.warning('hcitool not found, sending vendor HCI command via raw socket')
                payload = bytes(int(b, 16) for b in reversed(bt_addr.split(':')))
                await utils.hci_send_cmd(int(adapter_idx or 0), ogf=0x3f, ocf=0x001, data=payload)
        else:
            return False

        # Reset the adapter. btmgmt is the modern replacement for `hciconfig hci0 reset`.
        if _has_cmd('btmgmt'):
            await utils.run_system_command(f'btmgmt --index {adapter_idx} power off')
            await utils.run_system_command(f'btmgmt --index {adapter_idx} power on')
        elif _has_cmd('hciconfig'):
            logger.warning('btmgmt not found, falling back to deprecated hciconfig for adapter reset')
            await utils.run_system_command(f'hciconfig {self._adapter_name} reset')
        else:
            logger.warning('Neither btmgmt nor hciconfig found, attempting reset via DBus')
            self.powered(False)
            self.powered(True)
        await utils.run_system_command("systemctl restart bluetooth.service")

        # now we have to reget all dbus-shenanigans because we just restarted it's service.
        self.__init__(self._device_id)

        if self.get_address() != bt_addr:
            logger.info("Failed to set btaddr")
            return False
        else:
            logger.info(f"Changed bt_addr to {bt_addr}")
            return True

    def get_paired_switches(self):
        switches = []
        for path, ifaces in dbus.SystemBus().get_object('org.bluez', '/').GetManagedObjects('org.freedesktop.DBus.ObjectManager', dbus_interface='org.freedesktop.DBus.ObjectManager').items():
            d = ifaces.get("org.bluez.Device1")
            if d and d['Name'] == "Nintendo Switch":
                switches += [path]
        return switches

    def unpair_path(self, path):
        self.adapter.RemoveDevice(path)

    def powered(self, boolean=True):
        self.properties.Set(self.adapter.dbus_interface, 'Powered', boolean)

    def discoverable(self, boolean=True):
        """
        Make adapter discoverable, starts advertising.
        """
        self.properties.Set(self.adapter.dbus_interface, 'Discoverable', boolean)

    def pairable(self, boolean=True):
        """
        Make adapter pairable
        """
        self.properties.Set(self.adapter.dbus_interface, 'Pairable', boolean)

    async def set_class(self, cls='0x002508'):
        """
        Sets Bluetooth device class. Prefers btmgmt (modern bluez-tools);
        falls back to the deprecated hciconfig if needed.
        :param cls: default 0x002508 (Gamepad/joystick device class)
        """
        logger.info(f'setting device class to {cls}...')
        cls_int = int(cls, base=0)
        adapter_idx = self._adapter_name.replace('hci', '')
        # Decompose 24-bit class. btmgmt sets bits 0-12 (minor byte + major 5-bit).
        # Service class bits 13-23 are derived by bluez from registered profiles
        # and discoverability state, so we can't set them directly via btmgmt.
        minor = cls_int & 0xFF
        major = (cls_int >> 8) & 0x1F

        used_btmgmt = False
        if _has_cmd('btmgmt'):
            rc, _, _ = await utils.run_system_command(f'btmgmt --index {adapter_idx} class {major} {minor}')
            used_btmgmt = (rc == 0)
        if not used_btmgmt:
            if _has_cmd('hciconfig'):
                logger.warning('btmgmt unavailable or failed; falling back to deprecated hciconfig')
                await utils.run_system_command(f'hciconfig {self._adapter_name} class {cls}')
            else:
                logger.error('Neither btmgmt nor hciconfig is available; cannot set device class.')
                return

        actual = self.properties.Get(self.adapter.dbus_interface, "Class")
        if actual != cls_int:
            # Service-class bits often differ when set via btmgmt; only the device-class
            # portion (bits 0-12) is required for the Switch to recognize the controller.
            if (actual & 0x1FFF) == (cls_int & 0x1FFF):
                logger.debug(f"device class set to {hex(actual)} (service bits differ from {cls}, this is expected)")
            else:
                logger.error(f"Could not set class to the required {cls}. Connecting probably won't work.")

    async def set_name(self, name: str):
        """
        Set Bluetooth device name.
        :param name: to set.
        """
        logger.info(f'setting device name to {name}...')
        self.properties.Set(self.adapter.dbus_interface, 'Alias', name)

    def get_UUIDs(self):
        return self.properties.Get(self.adapter.dbus_interface, "UUIDs")

    @staticmethod
    def register_sdp_record(record_path):
        _uuid = str(uuid.uuid4())

        with open(record_path) as record:
            opts = {
                'ServiceRecord': record.read(),
                'Role': 'server',
                'Service': HID_UUID,
                'RequireAuthentication': False,
                'RequireAuthorization': False
            }
            bus = dbus.SystemBus()
            manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
            manager.RegisterProfile(HID_PATH, _uuid, opts)

    @staticmethod
    def get_address_of_paired_path(path):
        return str(dbus.SystemBus().get_object('org.bluez', path).Get('org.bluez.Device1', "Address", dbus_interface='org.freedesktop.DBus.Properties'))
