"""Test fixtures for the Steamist integration."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_aio_discovery() -> Generator[MagicMock]:
    """Mock AIODiscovery30303."""
    with patch(
        "homeassistant.components.steamist.discovery.AIODiscovery30303"
    ) as mock_aio_discovery:
        mock_aio_discovery.return_value.async_scan = AsyncMock()
        yield mock_aio_discovery


@pytest.fixture(autouse=True)
def mock_udp_discover() -> Generator[AsyncMock]:
    """Avoid real UDP stdisc broadcasts unless a test patches discovery."""
    with patch(
        "homeassistant.components.steamist.discovery.async_udp_discover",
        AsyncMock(return_value=[]),
    ) as mock:
        yield mock
