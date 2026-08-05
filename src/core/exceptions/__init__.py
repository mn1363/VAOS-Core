"""Exception hierarchy shared across every VAOS layer."""

from core.exceptions.application_exceptions import (
    ApplicationError,
    PipelineExecutionError,
    UseCaseExecutionError,
)
from core.exceptions.base import VAOSError
from core.exceptions.domain_exceptions import (
    DomainError,
    EntityNotFoundError,
    EntityValidationError,
)
from core.exceptions.infrastructure_exceptions import (
    DependencyResolutionError,
    InfrastructureError,
    PluginError,
    StorageConnectionError,
)

__all__ = [
    "ApplicationError",
    "DependencyResolutionError",
    "DomainError",
    "EntityNotFoundError",
    "EntityValidationError",
    "InfrastructureError",
    "PipelineExecutionError",
    "PluginError",
    "StorageConnectionError",
    "UseCaseExecutionError",
    "VAOSError",
]
