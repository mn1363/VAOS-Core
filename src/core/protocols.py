"""Structural typing contracts shared across every VAOS layer.

Protocols defined here describe a capability -- not a concrete type -- so
outer layers can depend on a shape rather than on a specific class. This
keeps `core` free of any dependency on `domain`, `application`, or any
other layer while still giving every layer a common vocabulary to
implement against. All protocols are `@runtime_checkable`, so `isinstance`
checks work; note that `runtime_checkable` only verifies that the named
methods exist, not that their signatures match.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SupportsClose(Protocol):
    """An object that can release its resources synchronously."""

    def close(self) -> None:
        """Release any resources held by this object."""
        ...


@runtime_checkable
class SupportsAsyncClose(Protocol):
    """An object that can release its resources asynchronously."""

    async def aclose(self) -> None:
        """Release any resources held by this object."""
        ...


@runtime_checkable
class SupportsHealthCheck(Protocol):
    """An object that can report whether it is currently healthy."""

    async def health_check(self) -> bool:
        """Report whether this object is currently healthy.

        Returns:
            True if the object is healthy and ready to serve requests.
        """
        ...


@runtime_checkable
class SupportsLifecycle(Protocol):
    """An object with an explicit start/stop lifecycle.

    Intended for services registered with the future `bootstrap` and
    `runtime` packages, which start every registered service on startup
    and stop them, in reverse order, on shutdown.
    """

    async def start(self) -> None:
        """Start the object, acquiring any resources it needs."""
        ...

    async def stop(self) -> None:
        """Stop the object, releasing any resources it acquired."""
        ...
