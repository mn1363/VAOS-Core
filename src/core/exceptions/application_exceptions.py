"""Exceptions raised by the application layer."""

from core.exceptions.base import VAOSError


class ApplicationError(VAOSError):
    """Base class for errors originating from application use cases."""


class UseCaseExecutionError(ApplicationError):
    """Raised when a use case fails to complete successfully."""

    def __init__(self, use_case_name: str, reason: str) -> None:
        """Initialize the error with the failing use case and reason.

        Args:
            use_case_name: Name of the use case that failed.
            reason: Human-readable explanation of the failure.
        """
        super().__init__(f"Use case '{use_case_name}' failed: {reason}")
        self.use_case_name = use_case_name
        self.reason = reason


class PipelineExecutionError(ApplicationError):
    """Raised when a pipeline stage fails during execution."""

    def __init__(self, stage_name: str, reason: str) -> None:
        """Initialize the error with the failing stage and reason.

        Args:
            stage_name: Name of the pipeline stage that failed.
            reason: Human-readable explanation of the failure.
        """
        super().__init__(f"Pipeline stage '{stage_name}' failed: {reason}")
        self.stage_name = stage_name
        self.reason = reason
