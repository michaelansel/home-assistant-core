"""Support for Steamist sensors."""

from aiosteamist import SteamistStatus

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MODEL, CONF_PROTOCOL
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import PROTOCOL_UDP
from .coordinator import SteamistDataUpdateCoordinator
from .udp import SteamistExtendedStatus


class SteamistEntity(CoordinatorEntity[SteamistDataUpdateCoordinator], Entity):
    """Representation of a Steamist entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SteamistDataUpdateCoordinator,
        entry: ConfigEntry,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        if entry.unique_id:  # Only present if UDP broadcast works
            self._attr_device_info = DeviceInfo(
                connections={(dr.CONNECTION_NETWORK_MAC, entry.unique_id)},
                manufacturer="Steamist",
                model=entry.data[CONF_MODEL],
                # UDP-only firmwares do not serve a web page
                configuration_url=None
                if entry.data.get(CONF_PROTOCOL) == PROTOCOL_UDP
                else f"http://{entry.data[CONF_HOST]}",
                sw_version=coordinator.data.version
                if isinstance(coordinator.data, SteamistExtendedStatus)
                else None,
            )

    @property
    def _status(self) -> SteamistStatus:
        """Return the steamist status."""
        return self.coordinator.data
