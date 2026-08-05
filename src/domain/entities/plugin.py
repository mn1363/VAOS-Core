"""The `PluginDescriptor` entity: metadata describing a registered plugin."""

from dataclasses import dataclass

from domain.entities.base import Entity


@dataclass(eq=False, kw_only=True)
class PluginDescriptor(Entity):
    """Metadata describing a plugin known to the system.

    Attributes:
        name: Unique, stable name of the plugin.
        version: Semantic version string of the plugin.
        entry_point: Import path or identifier used to load the plugin.
        enabled: Whether the plugin is currently active.
    """

    name: str
    version: str
    entry_point: str
    enabled: bool = True
