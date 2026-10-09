"""Diagnostics support for Steamist."""

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SteamistDataUpdateCoordinator
from .udp import SteamistUDP


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
        # stmaster is only answered by Wi-Fi versions 4.00 and newer, and
        # its format has not been confirmed, so capture it here
        master: dict[str, Any] | None
        try:
            master_status = await client.async_get_master_status()
        except TimeoutError:
            master = None
        else:
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
