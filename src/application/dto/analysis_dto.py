"""Data transfer objects representing `AnalysisResult` entities."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalysisResultDTO:
    """Flat, transport-friendly representation of an `AnalysisResult`.

    Attributes:
        id: Identifier of the analysis result.
        artifact_id: Identifier of the artifact the result belongs to.
        stage: Name of the pipeline stage that produced this result.
        status: Outcome status, as a plain string.
        score_value: Overall score value, if this stage produced a score.
        score_max_value: Maximum possible score value, if applicable.
    """

    id: UUID
    artifact_id: UUID
    stage: str
    status: str
    score_value: float | None = None
    score_max_value: float | None = None
