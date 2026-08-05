"""A minimal, dependency-free dependency injection container.

The container supports two registration lifetimes:

* Singleton: a single pre-built instance is returned on every resolution.
* Factory: a callable is invoked on every resolution to produce a new
  instance (or a memoized one, for factories that manage their own cache).

Registrations are keyed by type, which keeps resolution statically
checkable by tools such as mypy while remaining simple to reason about.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from core.exceptions.infrastructure_exceptions import DependencyResolutionError

T = TypeVar("T")


class Container:
    """Resolves dependencies registered as singletons or factories."""

    def __init__(self) -> None:
        """Initialize an empty container with no registrations."""
        self._singletons: dict[type[Any], Any] = {}
        self._factories: dict[type[Any], Callable[[], Any]] = {}

    def register_singleton(self, interface: type[T], instance: T) -> None:
        """Register a pre-built instance to be returned for `interface`.

        Args:
            interface: The type (typically an ABC or Protocol) other code
                will request when resolving this dependency.
            instance: The concrete instance to return on every resolution.
        """
        self._singletons[interface] = instance

    def register_factory(self, interface: type[T], factory: Callable[[], T]) -> None:
        """Register a factory callable used to produce `interface` instances.

        Args:
            interface: The type other code will request when resolving
                this dependency.
            factory: A zero-argument callable that produces a new instance.
        """
        self._factories[interface] = factory

    def resolve(self, interface: type[T]) -> T:
        """Resolve a previously registered dependency.

        Args:
            interface: The type to resolve.

        Returns:
            The singleton instance, or a freshly produced factory instance.

        Raises:
            DependencyResolutionError: If `interface` has not been registered.
        """
        if interface in self._singletons:
            return self._singletons[interface]  # type: ignore[return-value]
        if interface in self._factories:
            return self._factories[interface]()  # type: ignore[return-value]
        raise DependencyResolutionError(interface.__name__)

    def is_registered(self, interface: type[Any]) -> bool:
        """Check whether `interface` has a singleton or factory registration.

        Args:
            interface: The type to check.

        Returns:
            True if `interface` can currently be resolved, False otherwise.
        """
        return interface in self._singletons or interface in self._factories
