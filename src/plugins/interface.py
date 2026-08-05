"""The `Plugin` Port: the extension point every VAOS plugin implements."""

from abc import ABC, abstractmethod

from core.container.container import Container


class Plugin(ABC):
    """A self-contained unit of functionality that extends VAOS at runtime."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, stable name identifying this plugin.

        Returns:
            The plugin name.
        """
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string of this plugin.

        Returns:
            The plugin version.
        """
        ...

    @abstractmethod
    async def setup(self, container: Container) -> None:
        """Register the plugin's services into the application container.

        Args:
            container: The container to register services into.
        """
        ...

    @abstractmethod
    async def teardown(self) -> None:
        """Release any resources acquired during `setup`."""
        ...
