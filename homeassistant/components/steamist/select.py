"""Support for Steamist steam preset selection."""

from typing import override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PROTOCOL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, PROTOCOL_UDP
from .coordinator import SteamistDataUpdateCoordinator
from .entity import SteamistEntity
from .udp import SteamistExtendedStatus, SteamistUDP

OPTION_OFF = "off"
PRESET_OPTIONS = {"preset_1": 1, "preset_2": 2}

STEAM_PRESET_SELECT = SelectEntityDescription(
    key="steam_preset",
    translation_key="steam_preset",
    options=[OPTION_OFF, *PRESET_OPTIONS],
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the steam preset select for controls that speak UDP."""
    if config_entry.data.get(CONF_PROTOCOL) != PROTOCOL_UDP:
        return
    # Uses legacy hass.data[DOMAIN] pattern
    # pylint: disable-next=home-assistant-use-runtime-data
    coordinator: SteamistDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]
    async_add_entities(
        [SteamistPresetSelect(coordinator, config_entry, STEAM_PRESET_SELECT)]
    )


class SteamistPresetSelect(SteamistEntity, SelectEntity):
    """Select which steam preset (memory) is running."""

    @property
    @override
    def current_option(self) -> str | None:
        """Return the running preset."""
        status = self._status
        if not isinstance(status, SteamistExtendedStatus):
            return None
        if status.preset == 0:
            return OPTION_OFF
        for option, preset in PRESET_OPTIONS.items():
            if preset == status.preset:
                return option
        return None

    @override
    async def async_select_option(self, option: str) -> None:
        """Start a preset or turn the steam off."""
        client = self.coordinator.client
        assert isinstance(client, SteamistUDP)
        if option == OPTION_OFF:
            await client.async_turn_off_steam()
        else:
            await client.async_turn_on_steam(PRESET_OPTIONS[option])
        await self.coordinator.async_request_refresh()
