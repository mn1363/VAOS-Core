"""Data structures produced by the foundation bounded context."""

from dataclasses import dataclass, field
from uuid import UUID

from domain.value_objects.score import Score


@dataclass(frozen=True, slots=True)
class FoundationReport:
    """Summary of a complete, end-to-end artifact evaluation.

    Attributes:
        artifact_id: Identifier of the evaluated artifact.
        overall_score: Aggregate score for the artifact, if computed.
        stage_scores: Per-stage scores keyed by stage name.
    """

    artifact_id: UUID
    overall_score: Score | None = None
    stage_scores: dict[str, Score] = field(default_factory=dict)
