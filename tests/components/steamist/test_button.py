"""Tests for the Steamist button platform."""

import pytest

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from . import (
    MOCK_ASYNC_GET_STATUS_ACTIVE,
    MOCK_UDP_STATUS_OFF,
    UDP_MASTER_RESPONSE,
    UDP_MASTER_RESPONSE_SHOWER,
    _async_setup_entry_with_status,
    _async_setup_udp_entry,
)


@pytest.mark.usefixtures("mock_aio_discovery")
@pytest.mark.parametrize("preset", [1, 2])
async def test_shower_button_press(hass: HomeAssistant, preset: int) -> None:
    """Test pressing a shower button when ShowerSense is attached."""
    client, _ = await _async_setup_udp_entry(
        hass, MOCK_UDP_STATUS_OFF, UDP_MASTER_RESPONSE_SHOWER
    )
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: f"button.shower_start_shower_preset_{preset}"},
        blocking=True,
    )
    client.async_start_shower.assert_awaited_once_with(preset)


@pytest.mark.usefixtures("mock_aio_discovery")
@pytest.mark.parametrize(
    "master_response",
    [
        pytest.param(UDP_MASTER_RESPONSE, id="steam_only"),
        pytest.param(None, id="no_stmaster"),
    ],
)
async def test_no_shower_buttons_without_shower_sense(
    hass: HomeAssistant, master_response: bytes | None
) -> None:
    """Test the shower buttons need a ShowerSense valve."""
    await _async_setup_udp_entry(hass, MOCK_UDP_STATUS_OFF, master_response)
    assert hass.states.async_all(BUTTON_DOMAIN) == []


@pytest.mark.usefixtures("mock_aio_discovery")
async def test_no_buttons_for_http_controls(hass: HomeAssistant) -> None:
    """Test controls using the legacy http api do not get shower buttons."""
    await _async_setup_entry_with_status(hass, MOCK_ASYNC_GET_STATUS_ACTIVE)
    assert hass.states.async_all(BUTTON_DOMAIN) == []
