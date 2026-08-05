"""Unit tests for the dependency injection container."""

import pytest

from core.container.container import Container
from core.exceptions.infrastructure_exceptions import DependencyResolutionError


class _Greeter:
    """A trivial service used to exercise container registrations."""

    def greet(self) -> str:
        """Return a static greeting.

        Returns:
            A greeting string.
        """
        return "hello"


def test_register_and_resolve_singleton() -> None:
    """A registered singleton should be returned unchanged on resolution."""
    container = Container()
    instance = _Greeter()
    container.register_singleton(_Greeter, instance)
    assert container.resolve(_Greeter) is instance


def test_register_and_resolve_factory() -> None:
    """A registered factory should be invoked on every resolution."""
    container = Container()
    container.register_factory(_Greeter, _Greeter)
    first = container.resolve(_Greeter)
    second = container.resolve(_Greeter)
    assert isinstance(first, _Greeter)
    assert first is not second


def test_resolve_unregistered_raises() -> None:
    """Resolving an unregistered type should raise a typed error."""
    container = Container()
    with pytest.raises(DependencyResolutionError):
        container.resolve(_Greeter)
