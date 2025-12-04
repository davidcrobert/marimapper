import socket
from time import sleep
import enum
from functools import partial
import argparse


def artnet_set_args(parser):
    parser.add_argument("--fixture_count", default=216, help="The Fixture count")
    parser.add_argument("--base_universe", default=0, help="The base universe")
    parser.add_argument(
        "--channels_per_fixture", default=1, help="The channels per fixture"
    )
    parser.add_argument(
        "--server", default="255.255.255.255", help="The server address"
    )
    parser.add_argument("--broadcast", action="store_true", help="Whether to broadcast")


def artnet_backend_factory(args: argparse.Namespace):
    # Enable broadcast automatically when targeting the default broadcast address
    effective_broadcast = args.broadcast or args.server == "255.255.255.255"
    return partial(
        Backend,
        args.fixture_count,
        args.base_universe,
        args.channels_per_fixture,
        args.server,
        effective_broadcast,
    )


class OpCode(enum.Enum):
    # Abridged list of Art-Net OpCodes
    ArtDMX = 0x5000
    ArtSync = 0x5200


class Backend:
    """Backend for Art-Net devices.

    This backend assumes your fixtures are on consecutive Art-Net universes, with no gaps, and that
    they only have brightness channels. This should work with most common Art-Net LED drivers.

    To switch a fixture on, it'll set all the brightness channels for a fixture to full.

    https://art-net.org.uk/art-net-specification/
    """

    # Art-Net implementation constants
    UDP_PORT = 6454
    ARTNET_VERSION = 14

    def __init__(
        self,
        fixture_count: int,
        base_universe: int,
        channels_per_fixture: int,
        server_address: str,
        broadcast: bool,
    ):
        self.fixture_count = fixture_count
        self.base_universe = base_universe
        self.channels_per_fixture = channels_per_fixture
        self.server_address = server_address
        self.sequence = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Allow broadcast sockets so the default 255.255.255.255 target works on Windows
        if broadcast or server_address == "255.255.255.255":
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def get_led_count(self):
        return self.fixture_count

    def send_packet(self, packet: bytearray):
        self.sock.sendto(packet, (self.server_address, self.UDP_PORT))

    def artnet_header(self, opcode: OpCode) -> bytearray:
        packet = bytearray("Art-Net\0", "utf8")  # Header
        packet.extend(opcode.value.to_bytes(2, byteorder="little"))
        packet.extend(self.ARTNET_VERSION.to_bytes(2, byteorder="big"))
        return packet

    def get_artdmx_packet(
        self, universe: int, channels: list[int], sequence: int
    ) -> bytearray:
        packet = self.artnet_header(OpCode.ArtDMX)
        packet.append(sequence)  # Sequence
        packet.append(0)  # Physical

        # The Art-Net spec defines a more complex split of net/subnet/universe, but that only
        # starts to be a problem with huge setups, so we're merging all that into one universe ID
        # for the moment.
        universe += self.base_universe
        packet.extend(universe.to_bytes(2, byteorder="little"))

        length = len(channels)
        packet.extend(length.to_bytes(2, byteorder="big"))  # Length of data, MSB first
        packet.extend(channels)
        return packet

    def get_artsync_packet(self) -> bytearray:
        packet = self.artnet_header(OpCode.ArtSync)
        packet.extend([0, 0])
        return packet

    def send_universe(self, universe: int, channels: list[int]) -> None:
        packet = self.get_artdmx_packet(universe, channels, self.sequence)
        self.send_packet(packet)
        self.sequence = (self.sequence + 1) % 256

    def set_led(self, led_index: int, on: bool) -> None:
        # Calculate how many universes we need to cover all the LEDs
        universe_count = (self.get_led_count() * self.channels_per_fixture) // 512 + 1

        # Generate a zeroed list of all channels we need to send
        channels = [0] * (512 * universe_count)

        # Set the brightness for the selected fixture
        fixture_base_channel = led_index * self.channels_per_fixture
        for c in range(0, self.channels_per_fixture):
            channels[fixture_base_channel + c] = 255 if on else 0

        # Split the channels into universes
        universes = [
            channels[u * 512 : (u + 1) * 512] for u in range(0, universe_count)
        ]

        # Some Art-Net devices expect a constant stream of data and won't immediately update
        # if they only see a single packet. Ideally we would spawn a separate thread and keep sending
        # packets at 40Hz, but this works on my hardware, although it slows things down a bit.
        for _ in range(0, 5):
            for u in range(0, len(universes)):
                self.send_universe(u, universes[u])
            sleep(0.05)

        # Send an ArtSync packet for good measure, although I'm not sure many devices actually use it.
        self.send_packet(self.get_artsync_packet())

    def set_leds(self, updates) -> bool:
        """
        Bulk update LEDs. Accepts either:
        - Iterable of (index, value) tuples, where value can be bool/int or an RGB-like iterable.
        - Iterable of per-LED values (same length as LED count), used for compatibility with existing calls.
        """
        led_count = self.get_led_count()
        universe_count = (led_count * self.channels_per_fixture + 511) // 512
        channels = [0] * (512 * universe_count)

        def level_from(val):
            if isinstance(val, (list, tuple)):
                if len(val) == 0:
                    return 0
                try:
                    # Use the max channel value from RGB-like input
                    return max(0, min(255, int(max(val))))
                except Exception:
                    return 255 if bool(val) else 0
            if isinstance(val, bool):
                return 255 if val else 0
            try:
                return max(0, min(255, int(val)))
            except Exception:
                return 255 if bool(val) else 0

        # Determine format: tuple updates vs per-index list
        if updates and isinstance(updates[0], tuple) and len(updates[0]) == 2:
            iterable = updates
        else:
            iterable = enumerate(updates)

        for idx, val in iterable:
            if idx < 0 or idx >= led_count:
                continue
            level = level_from(val)
            base = idx * self.channels_per_fixture
            for c in range(self.channels_per_fixture):
                channels[base + c] = level

        universes = [channels[u * 512 : (u + 1) * 512] for u in range(universe_count)]

        # Mirror the multi-frame approach used in set_led to ensure devices latch
        for _ in range(0, 5):
            for u in range(universe_count):
                self.send_universe(u, universes[u])
            sleep(0.05)

        self.send_packet(self.get_artsync_packet())
        return True

    def blackout(self) -> bool:
        """Turn off all fixtures; send a few frames so controllers latch."""
        universe_count = (self.get_led_count() * self.channels_per_fixture + 511) // 512
        channels = [0] * (512 * universe_count)
        universes = [channels[u * 512 : (u + 1) * 512] for u in range(universe_count)]

        # Many Art-Net devices need multiple frames before updating; mirror set_led behaviour.
        for _ in range(0, 5):
            for u in range(universe_count):
                self.send_universe(u, universes[u])
            sleep(0.02)

        self.send_packet(self.get_artsync_packet())
        return True
