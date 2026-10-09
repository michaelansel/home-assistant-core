"""Support for Steamist ShowerSense preset buttons."""

from typing import override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PROTOCOL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, PROTOCOL_UDP
from .coordinator import SteamistDataUpdateCoordinator
from .entity import SteamistEntity
from .udp import SteamistUDP

# Only useful with a ShowerSense valve attached, which cannot be detected
# reliably yet, so these start disabled.
SHOWER_BUTTONS: tuple[tuple[ButtonEntityDescription, int], ...] = tuple(
    (
        ButtonEntityDescription(
            key=f"shower_preset_{preset}",
            translation_key=f"shower_preset_{preset}",
            entity_registry_enabled_default=False,
        ),
        preset,
    )
    for preset in (1, 2)
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the shower buttons for controls that speak UDP."""
    if config_entry.data.get(CONF_PROTOCOL) != PROTOCOL_UDP:
        return
    # Uses legacy hass.data[DOMAIN] pattern
    # pylint: disable-next=home-assistant-use-runtime-data
    coordinator: SteamistDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]
    async_add_entities(
        SteamistShowerButton(coordinator, config_entry, description, preset)
        for description, preset in SHOWER_BUTTONS
    )


class SteamistShowerButton(SteamistEntity, ButtonEntity):
    """Start a ShowerSense preset."""

    def __init__(
        self,
        coordinator: SteamistDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ButtonEntityDescription,
        preset: int,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, entry, description)
        self._preset = preset

    @override
    async def async_press(self) -> None:
        """Start the shower preset."""
        client = self.coordinator.client
        assert isinstance(client, SteamistUDP)
        await client.async_start_shower(self._preset)
        await self.coordinator.async_request_refresh()
