"""Diagnostics support for Steamist."""

from dataclasses import asdict
from typing import Any

from aiosteamist import SteamistUDP

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SteamistDataUpdateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # Uses legacy hass.data[DOMAIN] pattern
    # pylint: disable-next=home-assistant-use-runtime-data
    coordinator: SteamistDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    data: dict[str, Any] = {
        "entry": {"data": dict(entry.data), "unique_id": entry.unique_id},
        "status": asdict(coordinator.data) if coordinator.data else None,
    }
    client = coordinator.client
    if isinstance(client, SteamistUDP):
        master: dict[str, Any] | None = None
        if (master_status := coordinator.master_status) is not None:
            master = asdict(master_status)
            if master_status.peripherals is not None:
                master["peripherals"] = [
                    flag.name for flag in master_status.peripherals
                ]
        data["stmaster"] = master
        data["raw_responses"] = {
            command.decode(): response.decode("latin-1")
            for command, response in client.last_responses.items()
        }
    return data
