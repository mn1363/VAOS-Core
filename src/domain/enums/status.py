"""Status and stage enumerations shared across domain entities."""

from enum import StrEnum, auto


class ArtifactStatus(StrEnum):
    """Lifecycle status of an `Artifact`."""

    PENDING = auto()
    COLLECTED = auto()
    PROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()


class TaskStatus(StrEnum):
    """Lifecycle status of a `Task`."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class PipelineStageStatus(StrEnum):
    """Outcome status of a single pipeline stage execution."""

    PENDING = auto()
    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    SKIPPED = auto()


class AnalysisStage(StrEnum):
    """Named stages an artifact may pass through in a pipeline."""

    COLLECTION = auto()
    EXTRACTION = auto()
    ANALYSIS = auto()
    SCORING = auto()
    REPORTING = auto()
