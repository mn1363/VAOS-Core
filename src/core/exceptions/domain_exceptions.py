"""Exceptions raised by the domain layer."""

from core.exceptions.base import VAOSError


class DomainError(VAOSError):
    """Base class for errors originating from domain rules or invariants."""


class EntityNotFoundError(DomainError):
    """Raised when a requested domain entity cannot be located."""

    def __init__(self, entity_name: str, entity_id: str) -> None:
        """Initialize the error with the missing entity's identity.

        Args:
            entity_name: Name of the entity type that was not found.
            entity_id: Identifier that was looked up.
        """
        super().__init__(f"{entity_name} with id '{entity_id}' was not found")
        self.entity_name = entity_name
        self.entity_id = entity_id


class EntityValidationError(DomainError):
    """Raised when a domain entity fails to satisfy its invariants."""

    def __init__(self, entity_name: str, reason: str) -> None:
        """Initialize the error with the failing entity and reason.

        Args:
            entity_name: Name of the entity type that failed validation.
            reason: Human-readable explanation of the failure.
        """
        super().__init__(f"{entity_name} failed validation: {reason}")
        self.entity_name = entity_name
        self.reason = reason
