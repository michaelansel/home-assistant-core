"""The Steamist integration discovery."""

import asyncio
import logging
from typing import Any

from discovery30303 import AIODiscovery30303, Device30303

from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.const import CONF_MODEL, CONF_NAME, CONF_PROTOCOL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, discovery_flow
from homeassistant.util.network import is_ip_address

from .const import DISCOVER_SCAN_TIMEOUT, DISCOVERY, DOMAIN, PROTOCOL_UDP
from .udp import SteamistUDPStatus, async_discover as async_udp_discover

_LOGGER = logging.getLogger(__name__)


MODEL_450_HOSTNAME_PREFIX = "MY450-"
MODEL_550_HOSTNAME_PREFIX = "MY550-"
# Devices found with the mySteamist "stdisc" command have no hostname,
# so one is synthesized as STM<version>-<mac>
UDP_HOSTNAME_PREFIX = "STM"


@callback
def async_is_steamist_device(device: Device30303) -> bool:
    """Check if a 30303 discovery is a steamist device."""
    return device.hostname.startswith(
        (MODEL_450_HOSTNAME_PREFIX, MODEL_550_HOSTNAME_PREFIX, UDP_HOSTNAME_PREFIX)
    )


@callback
def async_is_udp_device(device: Device30303) -> bool:
    """Check if a discovered device only speaks the mySteamist UDP protocol."""
    return device.hostname.startswith(UDP_HOSTNAME_PREFIX)


@callback
def async_device_from_udp_status(ip: str, status: SteamistUDPStatus) -> Device30303:
    """Convert a stdisc response to a Device30303."""
    return Device30303(
        hostname=f"{UDP_HOSTNAME_PREFIX}{status.version}-{status.mac.replace(':', '')}",
        mac=status.mac,
        ipaddress=ip,
        name=status.name,
    )


@callback
def async_update_entry_from_discovery(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    device: Device30303,
) -> bool:
    """Update a config entry from a discovery."""
    data_updates: dict[str, Any] = {}
    updates: dict[str, Any] = {}
    if not entry.unique_id:
        updates["unique_id"] = dr.format_mac(device.mac)
    if not entry.data.get(CONF_NAME) or is_ip_address(entry.data[CONF_NAME]):
        updates["title"] = data_updates[CONF_NAME] = device.name
    if not entry.data.get(CONF_MODEL) and "-" in device.hostname:
        data_updates[CONF_MODEL] = device.hostname.split("-", maxsplit=1)[0]
    if async_is_udp_device(device) and entry.data.get(CONF_PROTOCOL) != PROTOCOL_UDP:
        data_updates[CONF_PROTOCOL] = PROTOCOL_UDP
    if data_updates:
        updates["data"] = {**entry.data, **data_updates}
    if updates:
        return hass.config_entries.async_update_entry(entry, **updates)
    return False


async def async_discover_devices(
    hass: HomeAssistant, timeout: int, address: str | None = None
) -> list[Device30303]:
    """Discover devices."""
    if address:
        targets = [address]
    else:
        targets = [
            str(broadcast_address)
            for broadcast_address in await network.async_get_ipv4_broadcast_addresses(
                hass
            )
        ]

    async def _async_udp_scan() -> list[tuple[str, SteamistUDPStatus]]:
        try:
            return await async_udp_discover(targets)
        except OSError as err:
            _LOGGER.debug("UDP stdisc scan failed with error: %s", err)
            return []

    scanner = AIODiscovery30303()
    udp_results, results = await asyncio.gather(
        _async_udp_scan(),
        asyncio.gather(
            *[
                scanner.async_scan(timeout=timeout, address=target_address)
                for target_address in targets
            ],
            return_exceptions=True,
        ),
    )
    for idx, discovered in enumerate(results):
        if isinstance(discovered, Exception):
            _LOGGER.debug("Scanning %s failed with error: %s", targets[idx], discovered)
            continue

    found_devices = list(scanner.found_devices)
    # Prefer the legacy discovery, which means the http api is available
    known_macs = {dr.format_mac(device.mac) for device in found_devices}
    found_devices.extend(
        async_device_from_udp_status(ip, status)
        for ip, status in udp_results
        if dr.format_mac(status.mac) not in known_macs
    )

    _LOGGER.debug("Found devices: %s", found_devices)
    if not address:
        return [device for device in found_devices if async_is_steamist_device(device)]

    return [device for device in found_devices if device.ipaddress == address]


@callback
def async_find_discovery_by_ip(
    discoveries: list[Device30303], host: str
) -> Device30303 | None:
    """Search a list of discoveries for one with a matching ip."""
    for discovery in discoveries:
        if discovery.ipaddress == host:
            return discovery
    return None


async def async_discover_device(hass: HomeAssistant, host: str) -> Device30303 | None:
    """Direct discovery to a single ip instead of broadcast."""
    return async_find_discovery_by_ip(
        await async_discover_devices(hass, DISCOVER_SCAN_TIMEOUT, host), host
    )


@callback
def async_get_discovery(hass: HomeAssistant, host: str) -> Device30303 | None:
    """Check if a device was already discovered via a broadcast discovery."""
    # Uses legacy hass.data[DOMAIN] pattern
    # pylint: disable-next=home-assistant-use-runtime-data
    discoveries: list[Device30303] = hass.data[DOMAIN][DISCOVERY]
    return async_find_discovery_by_ip(discoveries, host)


@callback
def async_trigger_discovery(
    hass: HomeAssistant,
    discovered_devices: list[Device30303],
) -> None:
    """Trigger config flows for discovered devices."""
    for device in discovered_devices:
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data={
                "ipaddress": device.ipaddress,
                "name": device.name,
                "mac": device.mac,
                "hostname": device.hostname,
            },
        )
