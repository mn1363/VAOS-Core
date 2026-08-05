"""Shared exception hierarchy for VAOS.

`VAOSError` is the root of every exception explicitly raised by VAOS code.
Catching it lets callers distinguish documented VAOS failures from
unexpected third-party or runtime errors. Every layer built on top of
`core` is expected to raise one of the categories below -- or a subclass
of one, defined in its own package -- rather than a bare `Exception` or an
unrelated hierarchy.
"""

from collections.abc import Mapping
from typing import Any


class VAOSError(Exception):
    """Base class for every exception explicitly raised by VAOS.

    Attributes:
        message: Human-readable description of what went wrong.
        details: Structured context about the failure, useful for logging
            or API error responses. Empty when no extra context applies.
    """

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        """Initialize the error.

        Args:
            message: Human-readable description of what went wrong.
            details: Optional structured context about the failure.
        """
        super().__init__(message)
        self.message = message
        self.details: Mapping[str, Any] = details or {}

    def __str__(self) -> str:
        """Render the error as its plain message, ignoring structured details.

        Returns:
            The human-readable message passed at construction time.
        """
        return self.message


class ConfigurationError(VAOSError):
    """Raised when configuration cannot be loaded, parsed, or applied."""


class ValidationError(VAOSError):
    """Raised when a value fails validation against its expected constraints."""


class NotFoundError(VAOSError):
    """Raised when a requested resource cannot be located."""
