"""Application bootstrap sequence.

Bootstrap order:
    1. Load settings from the environment.
    2. Configure logging using the loaded settings.
    3. Create an empty dependency injection container.
    4. Register the core, framework-level services (settings, logger).
    5. Return the settings and container to the caller, which -- as the
       composition root -- registers domain-specific services such as
       plugins, repositories and pipelines.

`core.bootstrap` intentionally knows nothing about domain, application,
infrastructure, or plugin packages: only outward-facing entrypoints
(`api`, `cli`) are allowed to depend on every layer, which keeps the
dependency direction pointing inward.
"""

from collections.abc import Mapping

from core.config.loader import load_settings
from core.config.settings import Settings
from core.container.container import Container
from core.container.providers import register_core_services
from core.logging.logger import configure_logging


def bootstrap(env: Mapping[str, str] | None = None) -> tuple[Settings, Container]:
    """Run the core bootstrap sequence and return settings plus a container.

    Args:
        env: Optional environment mapping to load settings from. Defaults
            to `os.environ` when omitted.

    Returns:
        A tuple of the resolved `Settings` and a `Container` pre-populated
        with core services only.
    """
    settings = load_settings(env)
    configure_logging(settings.logging)
    container = Container()
    register_core_services(container, settings)
    return settings, container
