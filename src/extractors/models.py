"""Data structures produced by `Extractor` implementations."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    """Outcome of a single extraction attempt against an artifact.

    Attributes:
        artifact_id: Identifier of the artifact that was processed.
        succeeded: Whether the extraction attempt completed successfully.
        extracted: Freeform structured data extracted from the artifact.
        error_message: Explanation of the failure, when `succeeded` is False.
    """

    artifact_id: UUID
    succeeded: bool
    extracted: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
