"""The `PluginRegistry`: tracks plugins known to the running application."""

from core.exceptions.infrastructure_exceptions import PluginError
from core.logging.logger import get_logger
from plugins.interface import Plugin

_logger = get_logger("plugins.registry")


class PluginRegistry:
    """Maintains the set of plugins registered with the application."""

    def __init__(self) -> None:
        """Initialize an empty plugin registry."""
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        """Add a plugin to the registry.

        Args:
            plugin: The plugin instance to register.

        Raises:
            PluginError: If a plugin with the same name is already registered.
        """
        if plugin.name in self._plugins:
            raise PluginError(plugin.name, "a plugin with this name is already registered")
        self._plugins[plugin.name] = plugin
        _logger.info("Registered plugin '%s' v%s", plugin.name, plugin.version)

    def get(self, name: str) -> Plugin:
        """Retrieve a registered plugin by name.

        Args:
            name: Name of the plugin to retrieve.

        Returns:
            The registered plugin instance.

        Raises:
            PluginError: If no plugin with the given name is registered.
        """
        try:
            return self._plugins[name]
        except KeyError as exc:
            raise PluginError(name, "no plugin with this name is registered") from exc

    def list_plugins(self) -> list[Plugin]:
        """List every currently registered plugin.

        Returns:
            A list of every registered plugin instance.
        """
        return list(self._plugins.values())
