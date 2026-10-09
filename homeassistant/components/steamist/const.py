"""Constants for the Steamist integration."""

from xml.parsers.expat import ExpatError

import aiohttp

DOMAIN = "steamist"

CONNECTION_EXCEPTIONS = (TimeoutError, aiohttp.ClientError)
HTTP_EXCEPTIONS = (*CONNECTION_EXCEPTIONS, ExpatError, KeyError)

PROTOCOL_UDP = "udp"

STARTUP_SCAN_TIMEOUT = 5
DISCOVER_SCAN_TIMEOUT = 10

DISCOVERY = "discovery"
