"""The `AnalysisResult` entity: the outcome of processing an artifact."""

from dataclasses import dataclass
from uuid import UUID

from domain.entities.base import Entity
from domain.enums.status import AnalysisStage, PipelineStageStatus
from domain.value_objects.score import Score


@dataclass(eq=False, kw_only=True)
class AnalysisResult(Entity):
    """The recorded outcome of a single pipeline stage applied to an artifact.

    Attributes:
        artifact_id: Identifier of the `Artifact` this result belongs to.
        stage: Pipeline stage that produced this result.
        status: Outcome status of the stage execution.
        score: Optional score attached to this result, when the stage is
            a scoring stage.
    """

    artifact_id: UUID
    stage: AnalysisStage
    status: PipelineStageStatus = PipelineStageStatus.PENDING
    score: Score | None = None
