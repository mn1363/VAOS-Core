"""Smoke tests for the core bootstrap sequence."""

from core.config.settings import Settings
from core.container.container import Container


def test_bootstrap_returns_settings_and_container(
    bootstrapped: tuple[Settings, Container],
) -> None:
    """Bootstrapping should return a `Settings` instance and a `Container`."""
    settings, container = bootstrapped
    assert isinstance(settings, Settings)
    assert isinstance(container, Container)


def test_bootstrap_registers_settings_singleton(
    bootstrapped: tuple[Settings, Container],
) -> None:
    """The bootstrapped container should resolve the `Settings` singleton."""
    settings, container = bootstrapped
    assert container.resolve(Settings) is settings
