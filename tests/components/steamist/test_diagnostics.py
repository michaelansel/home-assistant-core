"""Tests for the Steamist diagnostics."""

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant

from . import (
    MOCK_ASYNC_GET_STATUS_ACTIVE,
    MOCK_UDP_STATUS_PRESET_1,
    _async_setup_entry_with_status,
    _async_setup_udp_entry,
)

from tests.components.diagnostics import get_diagnostics_for_config_entry
from tests.typing import ClientSessionGenerator


@pytest.mark.usefixtures("mock_aio_discovery")
async def test_udp_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    snapshot: SnapshotAssertion,
) -> None:
    """Test diagnostics for a UDP control include the raw responses."""
    _, entry = await _async_setup_udp_entry(hass, MOCK_UDP_STATUS_PRESET_1)
    assert await get_diagnostics_for_config_entry(hass, hass_client, entry) == snapshot


@pytest.mark.usefixtures("mock_aio_discovery")
async def test_udp_diagnostics_no_stmaster(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Test diagnostics when the control does not answer stmaster."""
    client, entry = await _async_setup_udp_entry(hass, MOCK_UDP_STATUS_PRESET_1)
    client.async_get_master_status.side_effect = TimeoutError
    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert result["stmaster"] is None


@pytest.mark.usefixtures("mock_aio_discovery")
async def test_http_diagnostics(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Test diagnostics for a legacy http control."""
    _, entry = await _async_setup_entry_with_status(hass, MOCK_ASYNC_GET_STATUS_ACTIVE)
    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert result["status"] == {
        "active": True,
        "minutes_remain": 14,
        "temp": 102,
        "temp_units": "F",
    }
    assert "stmaster" not in result
