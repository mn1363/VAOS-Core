"""FastAPI dependency-injection glue between `core.Container` and requests."""

from typing import Annotated

from fastapi import Depends, Request

from core.container.container import Container
from plugins.registry import PluginRegistry


def get_container(request: Request) -> Container:
    """Retrieve the application's DI container from request state.

    Args:
        request: The incoming HTTP request.

    Returns:
        The `Container` instance attached to the running application.
    """
    return request.app.state.container


def get_plugin_registry(
    container: Annotated[Container, Depends(get_container)],
) -> PluginRegistry:
    """Resolve the `PluginRegistry` from the application container.

    Args:
        container: The application's DI container.

    Returns:
        The registered `PluginRegistry` instance.
    """
    return container.resolve(PluginRegistry)
