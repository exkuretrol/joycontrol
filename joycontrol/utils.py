import asyncio
import logging
import socket
import struct
from contextlib import contextmanager

import hid

logger = logging.getLogger(__name__)


class AsyncHID(hid.Device):
    def __init__(self, *args, loop=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._loop = loop if loop is not None else asyncio.get_running_loop()

        self._write_lock = asyncio.Lock()
        self._read_lock = asyncio.Lock()

    async def read(self, size, timeout=None):
        async with self._read_lock:
            return await self._loop.run_in_executor(None, hid.Device.read, self, size, timeout)

    async def write(self, data):
        async with self._write_lock:
            return await self._loop.run_in_executor(None, hid.Device.write, self, data)


@contextmanager
def get_output(path=None, open_flags='wb', default=None):
    """
    Context manager that open the file a path was given, otherwise returns default value.
    """
    if path is not None:
        file = open(path, open_flags)
        yield file
        file.close()
    else:
        yield default


def get_bit(value, n):
    return (value >> n & 1) != 0


def flip_bit(value, n):
    return value ^ (1 << n)


def create_error_check_callback(ignore=None):
    """
    Creates callback causing errors of a finished future to be raised.
    Useful for debugging futures that are never awaited.
    :param ignore: Any number of errors to ignore.
    :returns callback which can be added to a future with future.add_done_callback(...)
    """
    def callback(future):
        if ignore:
            try:
                future.result()
            except ignore:
                # ignore suppressed errors
                pass
        else:
            future.result()
    return callback


async def run_system_command(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()

    logger.debug(f'[{cmd!r} exited with {proc.returncode}]')
    if stdout:
        logger.debug(f'[stdout]\n{stdout.decode()}')
    if stderr:
        logger.debug(f'[stderr]\n{stderr.decode()}')

    return proc.returncode, stdout, stderr

def start_asyncio_thread(func, ignore=None):
    """
    Yes, these are not actual threads. But for all asyncio intents and purposes
    they behave like they are.
    """
    out = asyncio.ensure_future(func)
    out.add_done_callback(
        create_error_check_callback(ignore=ignore)
    )
    return out

async def aio_chain(*args):
    for a in args:
        await a

async def hci_send_cmd(adapter_index: int, ogf: int, ocf: int, data: bytes = b'') -> None:
    """
    Send a raw HCI command via an HCI raw socket. Modern alternative to `hcitool cmd`
    when bluez-tools are not installed. Fire-and-forget — does not parse the event response.
    Requires root and the bluetooth kernel module loaded.
    :param adapter_index: integer adapter index (0 for hci0)
    :param ogf: OpCode Group Field (6 bits)
    :param ocf: OpCode Command Field (10 bits)
    :param data: command parameters
    """
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
    try:
        sock.setblocking(False)
        await loop.run_in_executor(None, sock.bind, (adapter_index,))
        opcode = ((ogf & 0x3F) << 10) | (ocf & 0x3FF)
        # HCI command packet: type=0x01 | opcode (LE) | param_len | params
        pkt = struct.pack('<BHB', 0x01, opcode, len(data)) + data
        await loop.sock_sendall(sock, pkt)
    finally:
        sock.close()
