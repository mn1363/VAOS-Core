"""Data structures produced by `Scorer` implementations."""

from dataclasses import dataclass
from uuid import UUID

from domain.value_objects.score import Score


@dataclass(frozen=True, slots=True)
class ScoringOutcome:
    """Outcome of a single scoring attempt against an artifact.

    Attributes:
        artifact_id: Identifier of the artifact that was scored.
        succeeded: Whether the scoring attempt completed successfully.
        score: The computed score, when `succeeded` is True.
        error_message: Explanation of the failure, when `succeeded` is False.
    """

    artifact_id: UUID
    succeeded: bool
    score: Score | None = None
    error_message: str | None = None
