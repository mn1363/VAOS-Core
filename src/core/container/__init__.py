"""Dependency injection primitives: the container and core providers."""

from core.container.container import Container
from core.container.providers import register_core_services

__all__ = ["Container", "register_core_services"]
