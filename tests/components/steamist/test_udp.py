"""Tests for the Steamist UDP protocol."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest

from homeassistant.components.steamist import udp
from homeassistant.components.steamist.udp import (
    SteamistUDP,
    SteamistUDPError,
    parse_status,
)


@pytest.mark.parametrize(
    ("response", "temp", "preset", "minutes_remain", "active"),
    [
        (b"STM 550 72F0 00000-D0-CD-02-A2-8AShower", 72, 0, 0, False),
        (b"STM 550 73F1145000-D0-CD-02-A2-8AShower", 73, 1, 15, True),
        (b"STM 550 72F2145500-D0-CD-02-A2-8AShower\x00\x00", 72, 2, 15, True),
        (b"STM 550110F1 30000-D0-CD-02-A2-8AShower", 110, 1, 3, True),
    ],
)
def test_parse_status(
    response: bytes, temp: int, preset: int, minutes_remain: int, active: bool
) -> None:
    """Test parsing stdisc responses captured from a 550 control."""
    status = parse_status(response)
    assert status.version == "550"
    assert status.temp == temp
    assert status.temp_units == "F"
    assert status.preset == preset
    assert status.minutes_remain == minutes_remain
    assert status.active is active
    assert status.mac == "00:d0:cd:02:a2:8a"
    assert status.name == "Shower"


@pytest.mark.parametrize(
    "response", [b"", b"stdisc", b"Discovery: Who is out there?", b"STM garbage"]
)
def test_parse_status_invalid(response: bytes) -> None:
    """Test unexpected responses are rejected."""
    with pytest.raises(SteamistUDPError):
        parse_status(response)


class _FakeSteamist(asyncio.DatagramProtocol):
    """A fake control that answers stdisc and records button presses."""

    def __init__(self) -> None:
        self.preset = 0
        self.received: list[bytes] = []
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.received.append(data)
        if data == b"stdisc":
            assert self.transport is not None
            clock = "1450" if self.preset else " 000"
            self.transport.sendto(
                f"STM 550 72F{self.preset}{clock}00-D0-CD-02-A2-8AShower".encode(),
                addr,
            )
        elif data.startswith(b"stb"):
            self.preset = int(data[3:]) if data in (b"stb1", b"stb2") else 0


@pytest.fixture
async def fake_steamist(socket_enabled: None) -> AsyncGenerator[_FakeSteamist]:
    """Run a fake control on localhost."""
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _FakeSteamist, local_addr=("127.0.0.1", 0)
    )
    with patch.object(udp, "PORT", transport.get_extra_info("sockname")[1]):
        yield protocol
    transport.close()


async def test_client_round_trip(fake_steamist: _FakeSteamist) -> None:
    """Test status and button presses against a fake control."""
    client = SteamistUDP("127.0.0.1", timeout=0.5)
    status = await client.async_get_status()
    assert status.active is False
    assert status.temp == 72
    assert status.minutes_remain == 0

    await client.async_turn_on_steam()
    await asyncio.sleep(0.05)
    assert fake_steamist.received[-1] == b"stb1"
    status = await client.async_get_status()
    assert status.active is True
    assert status.minutes_remain == 15

    await client.async_turn_off_steam()
    await asyncio.sleep(0.05)
    assert fake_steamist.received[-1] == b"stb3"
    assert (await client.async_get_udp_status()).active is False

    with pytest.raises(ValueError):
        await client.async_turn_on_steam(preset=5)


async def test_client_transition_state(fake_steamist: _FakeSteamist) -> None:
    """Test the commanded state is reported until the device catches up."""
    client = SteamistUDP("127.0.0.1", timeout=0.5)
    await client.async_turn_on_steam()
    await asyncio.sleep(0.05)
    fake_steamist.preset = 0  # device has not caught up yet
    assert (await client.async_get_status()).active is True


@pytest.mark.usefixtures("socket_enabled")
async def test_client_timeout() -> None:
    """Test a device that never answers."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    try:
        with patch.object(udp, "PORT", transport.get_extra_info("sockname")[1]):
            client = SteamistUDP("127.0.0.1", timeout=0.1, attempts=2)
            with pytest.raises(TimeoutError):
                await client.async_get_status()
    finally:
        transport.close()


async def test_discover(fake_steamist: _FakeSteamist) -> None:
    """Test discovery collects stdisc responses."""
    devices = await udp.async_discover(["127.0.0.1"], timeout=0.2)
    assert len(devices) == 1
    ip, status = devices[0]
    assert ip == "127.0.0.1"
    assert status.name == "Shower"
