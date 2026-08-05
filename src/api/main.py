"""FastAPI application bootstrap: the API layer's composition root."""

from collections.abc import Mapping

from fastapi import FastAPI

from api.routers import health_router
from core.bootstrap import bootstrap
from infrastructure.composition import register_infrastructure
from plugins.registry import PluginRegistry


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    """Build and wire the FastAPI application.

    As the API layer's composition root, this function is responsible for
    running the core bootstrap sequence, registering infrastructure and
    plugin services, and attaching the resulting container to application
    state so request-scoped dependencies can resolve services from it.

    Args:
        env: Optional environment mapping used to load settings from.

    Returns:
        A fully configured `FastAPI` application instance.
    """
    settings, container = bootstrap(env)
    register_infrastructure(container, settings)
    container.register_singleton(PluginRegistry, PluginRegistry())

    app = FastAPI(title=settings.api.title, debug=settings.debug)
    app.state.settings = settings
    app.state.container = container
    app.include_router(health_router)
    return app


app = create_app()
