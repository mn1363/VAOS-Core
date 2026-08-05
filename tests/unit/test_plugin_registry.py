"""Unit tests for the plugin registry."""

import pytest

from core.container.container import Container
from core.exceptions.infrastructure_exceptions import PluginError
from plugins.interface import Plugin
from plugins.registry import PluginRegistry


class _StubPlugin(Plugin):
    """A minimal `Plugin` implementation used for testing the registry."""

    @property
    def name(self) -> str:
        """Return the stub plugin's name."""
        return "stub"

    @property
    def version(self) -> str:
        """Return the stub plugin's version."""
        return "0.1.0"

    async def setup(self, container: Container) -> None:
        """No-op setup for the stub plugin."""
        return

    async def teardown(self) -> None:
        """No-op teardown for the stub plugin."""
        return


def test_register_and_get_plugin() -> None:
    """A registered plugin should be retrievable by name."""
    registry = PluginRegistry()
    plugin = _StubPlugin()
    registry.register(plugin)
    assert registry.get("stub") is plugin


def test_register_duplicate_raises() -> None:
    """Registering two plugins with the same name should raise."""
    registry = PluginRegistry()
    registry.register(_StubPlugin())
    with pytest.raises(PluginError):
        registry.register(_StubPlugin())


def test_get_unknown_raises() -> None:
    """Retrieving an unregistered plugin name should raise."""
    registry = PluginRegistry()
    with pytest.raises(PluginError):
        registry.get("missing")
