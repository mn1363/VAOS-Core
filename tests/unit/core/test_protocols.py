"""Unit tests for `src.core.protocols`."""

from src.core.protocols import (
    SupportsAsyncClose,
    SupportsClose,
    SupportsHealthCheck,
    SupportsLifecycle,
)


class _Closeable:
    """A class implementing `SupportsClose`."""

    def close(self) -> None:
        """No-op close, present only to satisfy the protocol's shape."""
        return


class _AsyncCloseable:
    """A class implementing `SupportsAsyncClose`."""

    async def aclose(self) -> None:
        """No-op async close, present only to satisfy the protocol's shape."""
        return


class _HealthChecked:
    """A class implementing `SupportsHealthCheck`."""

    async def health_check(self) -> bool:
        """Always report healthy."""
        return True


class _Lifecycled:
    """A class implementing `SupportsLifecycle`."""

    async def start(self) -> None:
        """No-op start, present only to satisfy the protocol's shape."""
        return

    async def stop(self) -> None:
        """No-op stop, present only to satisfy the protocol's shape."""
        return


class _Plain:
    """A class implementing none of the Core protocols."""


def test_supports_close_structural_match() -> None:
    """A class with a matching `close` method should satisfy `SupportsClose`."""
    assert isinstance(_Closeable(), SupportsClose)
    assert not isinstance(_Plain(), SupportsClose)


def test_supports_async_close_structural_match() -> None:
    """A class with a matching `aclose` method should satisfy `SupportsAsyncClose`."""
    assert isinstance(_AsyncCloseable(), SupportsAsyncClose)
    assert not isinstance(_Plain(), SupportsAsyncClose)


def test_supports_health_check_structural_match() -> None:
    """A class with a matching `health_check` method should satisfy `SupportsHealthCheck`."""
    assert isinstance(_HealthChecked(), SupportsHealthCheck)
    assert not isinstance(_Plain(), SupportsHealthCheck)


def test_supports_lifecycle_structural_match() -> None:
    """A class with matching `start`/`stop` methods should satisfy `SupportsLifecycle`."""
    assert isinstance(_Lifecycled(), SupportsLifecycle)
    assert not isinstance(_Plain(), SupportsLifecycle)


def test_supports_lifecycle_requires_both_start_and_stop() -> None:
    """A class with only `start` (no `stop`) should not satisfy `SupportsLifecycle`."""

    class _OnlyStart:
        async def start(self) -> None:
            return None

    assert not isinstance(_OnlyStart(), SupportsLifecycle)
