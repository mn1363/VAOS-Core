"""Provider registration helpers for core, framework-level services.

Providers in this module wire only the services owned by the `core`
package itself (settings, logger). Outer layers (api, cli) are
responsible for registering their own services -- including plugins,
repositories and pipelines -- to keep the dependency direction pointing
inward, as required by Clean Architecture.
"""

import logging

from core.config.settings import Settings
from core.container.container import Container
from core.logging.logger import get_logger


def register_core_services(container: Container, settings: Settings) -> Container:
    """Register the framework-level services owned by `core`.

    Args:
        container: The container to populate.
        settings: The application settings to register and to derive the
            root logger from.

    Returns:
        The same container instance, for convenient chaining.
    """
    container.register_singleton(Settings, settings)
    container.register_singleton(logging.Logger, get_logger("vaos"))
    return container
