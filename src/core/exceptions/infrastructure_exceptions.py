"""Exceptions raised by the infrastructure layer and core services."""

from core.exceptions.base import VAOSError


class InfrastructureError(VAOSError):
    """Base class for errors originating from infrastructure concerns."""


class DependencyResolutionError(InfrastructureError):
    """Raised when the DI container cannot resolve a requested dependency."""

    def __init__(self, interface_name: str) -> None:
        """Initialize the error with the interface that could not be resolved.

        Args:
            interface_name: Name of the type that was requested.
        """
        super().__init__(f"No registration found for '{interface_name}'")
        self.interface_name = interface_name


class StorageConnectionError(InfrastructureError):
    """Raised when a storage backend cannot be reached."""

    def __init__(self, backend_name: str, reason: str) -> None:
        """Initialize the error with the backend and reason for failure.

        Args:
            backend_name: Name of the storage backend that was unreachable.
            reason: Human-readable explanation of the failure.
        """
        super().__init__(f"Could not connect to storage backend '{backend_name}': {reason}")
        self.backend_name = backend_name
        self.reason = reason


class PluginError(InfrastructureError):
    """Raised when a plugin fails to load, register, or initialize."""

    def __init__(self, plugin_name: str, reason: str) -> None:
        """Initialize the error with the offending plugin and reason.

        Args:
            plugin_name: Name of the plugin that failed.
            reason: Human-readable explanation of the failure.
        """
        super().__init__(f"Plugin '{plugin_name}' error: {reason}")
        self.plugin_name = plugin_name
        self.reason = reason
