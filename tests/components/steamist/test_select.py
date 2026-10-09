"""Tests for the Steamist select platform."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import (
    MOCK_ASYNC_GET_STATUS_ACTIVE,
    MOCK_UDP_STATUS_OFF,
    MOCK_UDP_STATUS_PRESET_1,
    _async_setup_entry_with_status,
    _async_setup_udp_entry,
)

from tests.common import async_fire_time_changed

ENTITY_ID = "select.shower_steam_preset"


@pytest.mark.usefixtures("mock_aio_discovery")
async def test_select_preset(hass: HomeAssistant) -> None:
    """Test selecting presets on a UDP control."""
    client, _ = await _async_setup_udp_entry(hass, MOCK_UDP_STATUS_PRESET_1)
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "preset_1"
    assert state.attributes["options"] == ["off", "preset_1", "preset_2"]

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_OPTION: "preset_2"},
        blocking=True,
    )
    client.async_turn_on_steam.assert_awaited_once_with(2)

    client.async_get_status = AsyncMock(return_value=MOCK_UDP_STATUS_OFF)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_OPTION: "off"},
        blocking=True,
    )
    client.async_turn_off_steam.assert_awaited_once()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == "off"


@pytest.mark.usefixtures("mock_aio_discovery")
async def test_select_unknown_preset(hass: HomeAssistant) -> None:
    """Test a preset the select does not know about, e.g. a shower memory."""
    status = MOCK_UDP_STATUS_PRESET_1.__class__(
        **{**MOCK_UDP_STATUS_PRESET_1.__dict__, "preset": 5}
    )
    await _async_setup_udp_entry(hass, status)
    assert hass.states.get(ENTITY_ID).state == "unknown"


@pytest.mark.usefixtures("mock_aio_discovery")
async def test_no_select_for_http_controls(hass: HomeAssistant) -> None:
    """Test controls using the legacy http api do not get a select."""
    await _async_setup_entry_with_status(hass, MOCK_ASYNC_GET_STATUS_ACTIVE)
    assert hass.states.async_all(SELECT_DOMAIN) == []
