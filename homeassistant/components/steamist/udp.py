"""UDP protocol for Steamist controls that speak the mySteamist protocol.

Newer Steamist controls (e.g. 550 firmware 5.x) no longer serve the
``/status.xml`` web page and only talk to the mySteamist app over UDP
port 30303. The protocol is documented by Delta Faucet in the
"Steamist Wi-Fi - Home Automation Protocol" knowledge base article:

    stdisc   -> STMv1v1tttFu0m0sMACdev
                v1v1 = version of the Wi-Fi device (4 chars)
                ttt  = current temperature (3 chars, space padded)
                F    = temperature units, F or C
                u    = memory (preset) running, 0 when off
                0m0s = time remaining as MMSS (space padded)
                MAC  = MAC address, e.g. 00-D0-CD-02-A2-8A
                dev  = device name
    stmaster -> STMmtttFu0m0sPff  (Wi-Fi version 4.00 or greater)
                m    = major version of the master control
                P    = peripherals attached to the master control
                       bit0 steam, bit1 AromaSense, bit2 AudioSense,
                       bit3 ChromaSense, bit4 ShowerSense
                ff   = future use
    stb#     -> button press, no response
                0/3 = off, 1/2 = start steam 1/2, 5/6 = start shower 1/2

Example responses, from home-assistant/core#69082:

    STM 550 72F0 00000-D0-CD-02-A2-8AShower    (off)
    STM 550 73F1145000-D0-CD-02-A2-8AShower    (preset 1, 14:50 remaining)

No ``stmaster`` response has been captured yet, so the encoding of the
peripherals field is a best guess and the raw response is kept.

This module has no Home Assistant dependencies so it can move into a
library such as aiosteamist.
"""

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntFlag
import logging
import re
import socket
import time
from typing import override

from aiosteamist import SteamistStatus

_LOGGER = logging.getLogger(__name__)

PORT = 30303
DISCOVER_COMMAND = b"stdisc"
MASTER_COMMAND = b"stmaster"
OFF_COMMAND = b"stb3"
STEAM_PRESETS = {1: b"stb1", 2: b"stb2"}
SHOWER_PRESETS = {1: b"stb5", 2: b"stb6"}

DEFAULT_TIMEOUT = 2.0
DEFAULT_ATTEMPTS = 3
TRANSITION_TIME = 10.0
NEVER_TIME = -1200.0

_TEMP = r"(?P<temp>[ \d]{3})(?P<units>[FC])(?P<preset>\d)(?P<time>[ \d]{4})"
STATUS_REGEX = re.compile(
    rf"^STM(?P<version>.{{4}}){_TEMP}"
    r"(?P<mac>(?:[0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2})(?P<name>.*)$",
    re.DOTALL,
)
MASTER_REGEX = re.compile(rf"^STM(?P<master>.){_TEMP}(?P<rest>.*)$", re.DOTALL)


class Peripheral(IntFlag):
    """Peripherals attached to the master control."""

    STEAM = 1
    AROMA_SENSE = 2
    AUDIO_SENSE = 4
    CHROMA_SENSE = 8
    SHOWER_SENSE = 16


class SteamistUDPError(Exception):
    """Raised when a UDP response cannot be understood."""


def _parse_clock(clock: str) -> tuple[int, int]:
    clock = clock.replace(" ", "0")
    return int(clock[:2]), int(clock[2:])


def _parse_temp(temp: str) -> int | None:
    temp = temp.strip()
    return int(temp) if temp else None


@dataclass(frozen=True)
class SteamistUDPStatus:
    """A parsed ``stdisc`` response."""

    version: str
    temp: int | None
    temp_units: str
    preset: int
    minutes: int
    seconds: int
    mac: str
    name: str

    @property
    def active(self) -> bool:
        """Return if a preset is running."""
        return self.preset != 0

    @property
    def minutes_remain(self) -> int:
        """Return the minutes remaining, rounded up."""
        return self.minutes + (1 if self.seconds else 0)

    @property
    def seconds_remain(self) -> int:
        """Return the total seconds remaining."""
        return self.minutes * 60 + self.seconds


@dataclass(frozen=True)
class SteamistMasterStatus:
    """A parsed ``stmaster`` response."""

    master_version: str
    temp: int | None
    temp_units: str
    preset: int
    minutes: int
    seconds: int
    peripherals: Peripheral | None
    raw: str


@dataclass
class SteamistExtendedStatus(SteamistStatus):
    """Status with the extra fields only the UDP protocol provides."""

    preset: int
    seconds_remain: int
    version: str
    mac: str
    name: str


def parse_status(data: bytes) -> SteamistUDPStatus:
    """Parse a ``stdisc`` response."""
    text = data.decode("latin-1")
    if not (match := STATUS_REGEX.match(text)):
        raise SteamistUDPError(f"Unexpected stdisc response: {data!r}")
    minutes, seconds = _parse_clock(match["time"])
    return SteamistUDPStatus(
        version=match["version"].strip(),
        temp=_parse_temp(match["temp"]),
        temp_units=match["units"],
        preset=int(match["preset"]),
        minutes=minutes,
        seconds=seconds,
        mac=match["mac"].replace("-", ":").lower(),
        name=match["name"].split("\x00")[0].strip(),
    )


def _parse_peripherals(rest: str) -> Peripheral | None:
    """Best effort decode of the peripherals field.

    The documentation describes it as a bitmask without saying whether it
    is sent as a raw byte or as a hex digit.
    """
    if not rest:
        return None
    char = rest[0]
    if char in "0123456789abcdefABCDEF":
        return Peripheral(int(char, 16))
    return Peripheral(ord(char) & 0x1F)


def parse_master_status(data: bytes) -> SteamistMasterStatus:
    """Parse a ``stmaster`` response."""
    text = data.decode("latin-1")
    if STATUS_REGEX.match(text) or not (match := MASTER_REGEX.match(text)):
        raise SteamistUDPError(f"Unexpected stmaster response: {data!r}")
    minutes, seconds = _parse_clock(match["time"])
    return SteamistMasterStatus(
        master_version=match["master"].strip(),
        temp=_parse_temp(match["temp"]),
        temp_units=match["units"],
        preset=int(match["preset"]),
        minutes=minutes,
        seconds=seconds,
        peripherals=_parse_peripherals(match["rest"]),
        raw=text,
    )


class _CollectProtocol[_T](asyncio.DatagramProtocol):
    """Collect responses that the parser accepts."""

    def __init__(self, parser: Callable[[bytes], _T]) -> None:
        self.parser = parser
        self.responses: dict[str, tuple[_T, bytes]] = {}
        self.received = asyncio.Event()

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        _LOGGER.debug("%s <= %s", addr, data)
        try:
            parsed = self.parser(data)
        except SteamistUDPError:
            return
        self.responses[addr[0]] = (parsed, data)
        self.received.set()

    @override
    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)


def _create_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))
    sock.setblocking(False)
    return sock


async def _async_send[_T](
    targets: Iterable[str],
    payload: bytes,
    parser: Callable[[bytes], _T],
    timeout: float,
    attempts: int,
    stop_on_first: bool,
) -> dict[str, tuple[_T, bytes]]:
    """Send a payload to each target and collect parsed responses."""
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: _CollectProtocol(parser), sock=_create_socket()
    )
    targets = list(targets)
    try:
        for _ in range(attempts):
            protocol.received.clear()
            for target in targets:
                _LOGGER.debug("%s => %s", target, payload)
                transport.sendto(payload, (target, PORT))
            try:
                if stop_on_first:
                    async with asyncio.timeout(timeout):
                        await protocol.received.wait()
                    break
                await asyncio.sleep(timeout)
            except TimeoutError:
                continue
    finally:
        transport.close()
    return protocol.responses


async def async_discover(
    broadcast_addresses: Iterable[str], timeout: float = DEFAULT_TIMEOUT
) -> list[tuple[str, SteamistUDPStatus]]:
    """Broadcast ``stdisc`` and return (ip, status) for each responder."""
    responses = await _async_send(
        broadcast_addresses,
        DISCOVER_COMMAND,
        parse_status,
        timeout,
        1,
        stop_on_first=False,
    )
    return [(ip, status) for ip, (status, _) in responses.items()]


class SteamistUDP:
    """Client for a Steamist control that speaks the UDP protocol."""

    def __init__(
        self,
        host: str,
        timeout: float = DEFAULT_TIMEOUT,
        attempts: int = DEFAULT_ATTEMPTS,
    ) -> None:
        """Create the client."""
        self._host = host
        self._timeout = timeout
        self._attempts = attempts
        self._lock = asyncio.Lock()
        self._transition_complete_time = NEVER_TIME
        self._transition_state = False
        self.last_responses: dict[bytes, bytes] = {}

    @property
    def host(self) -> str:
        """Return the host."""
        return self._host

    async def _async_request[_T](
        self, payload: bytes, parser: Callable[[bytes], _T]
    ) -> _T:
        async with self._lock:
            responses = await _async_send(
                [self._host],
                payload,
                parser,
                self._timeout,
                self._attempts,
                stop_on_first=True,
            )
        if self._host not in responses:
            raise TimeoutError(f"No {payload.decode()} response from {self._host}")
        parsed, raw = responses[self._host]
        self.last_responses[payload] = raw
        return parsed

    async def async_get_udp_status(self) -> SteamistUDPStatus:
        """Request and return the raw ``stdisc`` status."""
        return await self._async_request(DISCOVER_COMMAND, parse_status)

    async def async_get_master_status(self) -> SteamistMasterStatus:
        """Request the ``stmaster`` status (Wi-Fi version 4.00 or greater)."""
        return await self._async_request(MASTER_COMMAND, parse_master_status)

    async def async_get_status(self) -> SteamistExtendedStatus:
        """Return the status, compatible with the HTTP client's status."""
        status = await self.async_get_udp_status()
        if self._transition_complete_time > time.monotonic():
            active = self._transition_state
        else:
            active = status.active
        return SteamistExtendedStatus(
            temp=status.temp,
            temp_units=status.temp_units,
            minutes_remain=status.minutes_remain,
            active=active,
            preset=status.preset,
            seconds_remain=status.seconds_remain,
            version=status.version,
            mac=status.mac,
            name=status.name,
        )

    async def async_press_button(self, payload: bytes) -> None:
        """Send a button press, which the device does not acknowledge."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol, sock=_create_socket()
            )
            try:
                _LOGGER.debug("%s => %s", self._host, payload)
                transport.sendto(payload, (self._host, PORT))
            finally:
                transport.close()

    def _set_transition(self, state: bool) -> None:
        self._transition_state = state
        self._transition_complete_time = time.monotonic() + TRANSITION_TIME

    async def async_turn_on_steam(self, preset: int = 1) -> None:
        """Start steam using a preset (memory)."""
        if preset not in STEAM_PRESETS:
            raise ValueError(f"Invalid steam preset {preset}")
        await self.async_press_button(STEAM_PRESETS[preset])
        self._set_transition(True)

    async def async_turn_off_steam(self) -> None:
        """Turn the steam off."""
        await self.async_press_button(OFF_COMMAND)
        self._set_transition(False)

    async def async_start_shower(self, preset: int) -> None:
        """Start a ShowerSense preset (memory)."""
        if preset not in SHOWER_PRESETS:
            raise ValueError(f"Invalid shower preset {preset}")
        await self.async_press_button(SHOWER_PRESETS[preset])
