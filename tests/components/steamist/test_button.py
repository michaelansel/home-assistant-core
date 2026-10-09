"""Tests for the Steamist button platform."""

import pytest

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import (
    MOCK_ASYNC_GET_STATUS_ACTIVE,
    MOCK_UDP_STATUS_OFF,
    _async_setup_entry_with_status,
    _async_setup_udp_entry,
)


@pytest.mark.usefixtures("mock_aio_discovery")
async def test_shower_buttons_disabled_by_default(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Test the shower buttons start disabled."""
    await _async_setup_udp_entry(hass, MOCK_UDP_STATUS_OFF)
    for preset in (1, 2):
        entry = entity_registry.async_get(f"button.shower_start_shower_preset_{preset}")
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.usefixtures("mock_aio_discovery", "entity_registry_enabled_by_default")
@pytest.mark.parametrize("preset", [1, 2])
async def test_shower_button_press(hass: HomeAssistant, preset: int) -> None:
    """Test pressing a shower button."""
    client, _ = await _async_setup_udp_entry(hass, MOCK_UDP_STATUS_OFF)
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: f"button.shower_start_shower_preset_{preset}"},
        blocking=True,
    )
    client.async_start_shower.assert_awaited_once_with(preset)


@pytest.mark.usefixtures("mock_aio_discovery", "entity_registry_enabled_by_default")
async def test_no_buttons_for_http_controls(hass: HomeAssistant) -> None:
    """Test controls using the legacy http api do not get shower buttons."""
    await _async_setup_entry_with_status(hass, MOCK_ASYNC_GET_STATUS_ACTIVE)
    assert hass.states.async_all(BUTTON_DOMAIN) == []
