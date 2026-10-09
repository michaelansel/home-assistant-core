"""UDP protocol for Steamist controls that speak the mySteamist protocol.

Newer Steamist controls (e.g. 550 firmware 5.x) no longer serve the
``/status.xml`` web page and only talk to the mySteamist app over UDP
port 30303. The protocol is documented by Delta Faucet in the
"Steamist Wi-Fi - Home Automation Protocol" knowledge base article:

    stdisc  -> STMv1v1tttFu0m0sMACdev
               v1v1 = version of the Wi-Fi device (4 chars)
               ttt  = current temperature (3 chars, space padded)
               F    = temperature units, F or C
               u    = memory (preset) running, 0 when off
               0m0s = time remaining as MMSS (space padded)
               MAC  = MAC address, e.g. 00-D0-CD-02-A2-8A
               dev  = device name
    stb#    -> button press, no response
               0/3 = off, 1/2 = start steam 1/2, 5/6 = start shower 1/2

Example responses, from home-assistant/core#69082:

    STM 550 72F0 00000-D0-CD-02-A2-8AShower    (off)
    STM 550 73F1145000-D0-CD-02-A2-8AShower    (preset 1, 14:50 remaining)
"""

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
import logging
import re
import socket
import time
from typing import override

from aiosteamist import SteamistStatus

_LOGGER = logging.getLogger(__name__)

PORT = 30303
DISCOVER_COMMAND = b"stdisc"
OFF_COMMAND = b"stb3"
STEAM_COMMAND = b"stb%d"
STEAM_PRESETS = (1, 2)

DEFAULT_TIMEOUT = 2.0
DEFAULT_ATTEMPTS = 3
TRANSITION_TIME = 10.0
NEVER_TIME = -1200.0

STATUS_REGEX = re.compile(
    r"^STM(?P<version>.{4})(?P<temp>[ \d]{3})(?P<units>[FC])(?P<preset>\d)"
    r"(?P<time>[ \d]{4})(?P<mac>(?:[0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2})"
    r"(?P<name>.*)$",
    re.DOTALL,
)


class SteamistUDPError(Exception):
    """Raised when a UDP response cannot be understood."""


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


def parse_status(data: bytes) -> SteamistUDPStatus:
    """Parse a ``stdisc`` response."""
    text = data.decode("latin-1")
    if not (match := STATUS_REGEX.match(text)):
        raise SteamistUDPError(f"Unexpected response: {data!r}")
    temp = match["temp"].strip()
    clock = match["time"].replace(" ", "0")
    return SteamistUDPStatus(
        version=match["version"].strip(),
        temp=int(temp) if temp else None,
        temp_units=match["units"],
        preset=int(match["preset"]),
        minutes=int(clock[:2]),
        seconds=int(clock[2:]),
        mac=match["mac"].replace("-", ":").lower(),
        name=match["name"].split("\x00")[0].strip(),
    )


class _CollectProtocol(asyncio.DatagramProtocol):
    """Collect valid status responses."""

    def __init__(self) -> None:
        self.responses: dict[str, SteamistUDPStatus] = {}
        self.received = asyncio.Event()

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        _LOGGER.debug("%s <= %s", addr, data)
        try:
            status = parse_status(data)
        except SteamistUDPError:
            return
        self.responses[addr[0]] = status
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


async def _async_send(
    targets: Iterable[str],
    payload: bytes,
    timeout: float,
    attempts: int,
    stop_on_first: bool,
) -> dict[str, SteamistUDPStatus]:
    """Send a payload to each target and collect status responses."""
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _CollectProtocol, sock=_create_socket()
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
        broadcast_addresses, DISCOVER_COMMAND, timeout, 1, stop_on_first=False
    )
    return list(responses.items())


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

    async def async_get_udp_status(self) -> SteamistUDPStatus:
        """Request and return the raw status."""
        async with self._lock:
            responses = await _async_send(
                [self._host],
                DISCOVER_COMMAND,
                self._timeout,
                self._attempts,
                stop_on_first=True,
            )
        if self._host not in responses:
            raise TimeoutError(f"No response from {self._host}")
        return responses[self._host]

    async def async_get_status(self) -> SteamistStatus:
        """Return the status in the same shape as the HTTP client."""
        status = await self.async_get_udp_status()
        if self._transition_complete_time > time.monotonic():
            active = self._transition_state
        else:
            active = status.active
        return SteamistStatus(
            temp=status.temp,
            temp_units=status.temp_units,
            minutes_remain=status.minutes_remain,
            active=active,
        )

    async def _async_command(self, payload: bytes) -> None:
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
            raise ValueError(f"Invalid preset {preset}")
        await self._async_command(STEAM_COMMAND % preset)
        self._set_transition(True)

    async def async_turn_off_steam(self) -> None:
        """Turn the steam off."""
        await self._async_command(OFF_COMMAND)
        self._set_transition(False)
