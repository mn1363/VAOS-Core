"""Composition helpers for wiring infrastructure adapters into a container.

`register_infrastructure` is the single extension point outer layers
(api, cli) call during startup. It currently registers nothing, because
Phase 1 ships no concrete adapters -- it exists so later phases can add
registrations without changing any call site.
"""

from core.config.settings import Settings
from core.container.container import Container


def register_infrastructure(container: Container, settings: Settings) -> Container:
    """Register infrastructure adapters into `container`.

    Args:
        container: The container to populate with infrastructure services.
        settings: Application settings used to configure adapters.

    Returns:
        The same container instance, for convenient chaining.
    """
    return container
