"""Domain DTOs: flat, immutable snapshots of entities for transport across
layer boundaries (e.g. to a future API or CLI layer).

Every DTO is a frozen, slotted dataclass -- a point-in-time snapshot with
no lifecycle of its own, unlike the mutable `Entity` subclasses in
`entities.py` that own it. Each DTO provides a `from_entity` classmethod
that builds the snapshot from its corresponding entity.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .entities import AnalysisRun, Finding, SourceFile, SourceRepository


@dataclass(frozen=True, slots=True)
class SourceRepositoryDTO:
    """Flat, transport-friendly representation of a `SourceRepository`.

    Attributes:
        id: Identifier of the repository.
        name: Human-readable name of the repository.
        source_uri: Location the repository was collected from.
        provider: Where the repository was collected from, as a string.
        default_branch: Default branch analyzed for this repository.
        status: Current lifecycle status, as a string.
        metadata: Freeform metadata values.
        created_at: Timestamp the repository was first created.
        updated_at: Timestamp the repository was last modified.
    """

    id: UUID
    name: str
    source_uri: str
    provider: str
    default_branch: str
    status: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: SourceRepository) -> "SourceRepositoryDTO":
        """Build a DTO snapshot from a `SourceRepository` entity.

        Args:
            entity: The entity to snapshot.

        Returns:
            A flat, transport-friendly representation of `entity`.
        """
        return cls(
            id=entity.id,
            name=entity.name,
            source_uri=entity.source_uri,
            provider=str(entity.provider),
            default_branch=entity.default_branch,
            status=str(entity.status),
            metadata=dict(entity.metadata),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


@dataclass(frozen=True, slots=True)
class SourceFileDTO:
    """Flat, transport-friendly representation of a `SourceFile`.

    Attributes:
        id: Identifier of the file.
        repository_id: Identifier of the owning repository.
        relative_path: Path of the file relative to the repository root.
        language: Programming language of the file, as a string.
        size_bytes: Size of the file, in bytes.
        metadata: Freeform metadata values.
        created_at: Timestamp the file record was first created.
        updated_at: Timestamp the file record was last modified.
    """

    id: UUID
    repository_id: UUID
    relative_path: str
    language: str
    size_bytes: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: SourceFile) -> "SourceFileDTO":
        """Build a DTO snapshot from a `SourceFile` entity.

        Args:
            entity: The entity to snapshot.

        Returns:
            A flat, transport-friendly representation of `entity`.
        """
        return cls(
            id=entity.id,
            repository_id=entity.repository_id,
            relative_path=entity.relative_path,
            language=str(entity.language),
            size_bytes=entity.size_bytes,
            metadata=dict(entity.metadata),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


@dataclass(frozen=True, slots=True)
class AnalysisRunDTO:
    """Flat, transport-friendly representation of an `AnalysisRun`.

    Attributes:
        id: Identifier of the run.
        repository_id: Identifier of the repository being analyzed.
        status: Current lifecycle status, as a string.
        started_at: Timestamp the run started, if it has.
        completed_at: Timestamp the run reached a terminal status, if it
            has.
        duration_seconds: Elapsed run time, if the run has finished.
        error_message: Failure explanation, if the run failed.
        created_at: Timestamp the run record was first created.
        updated_at: Timestamp the run record was last modified.
    """

    id: UUID
    repository_id: UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: AnalysisRun) -> "AnalysisRunDTO":
        """Build a DTO snapshot from an `AnalysisRun` entity.

        Args:
            entity: The entity to snapshot.

        Returns:
            A flat, transport-friendly representation of `entity`.
        """
        return cls(
            id=entity.id,
            repository_id=entity.repository_id,
            status=str(entity.status),
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            duration_seconds=entity.duration_seconds,
            error_message=entity.error_message,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


@dataclass(frozen=True, slots=True)
class FindingDTO:
    """Flat, transport-friendly representation of a `Finding`.

    Attributes:
        id: Identifier of the finding.
        analysis_run_id: Identifier of the owning analysis run.
        source_file_id: Identifier of the specific file this finding is
            about, if any.
        category: Freeform label for the kind of finding this is.
        severity: Severity of the finding, as a string.
        message: Human-readable description of the finding.
        score: Optional numeric score associated with the finding.
        metadata: Freeform metadata values.
        created_at: Timestamp the finding was first created.
        updated_at: Timestamp the finding was last modified.
    """

    id: UUID
    analysis_run_id: UUID
    source_file_id: UUID | None
    category: str
    severity: str
    message: str
    score: float | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: Finding) -> "FindingDTO":
        """Build a DTO snapshot from a `Finding` entity.

        Args:
            entity: The entity to snapshot.

        Returns:
            A flat, transport-friendly representation of `entity`.
        """
        return cls(
            id=entity.id,
            analysis_run_id=entity.analysis_run_id,
            source_file_id=entity.source_file_id,
            category=entity.category,
            severity=str(entity.severity),
            message=entity.message,
            score=entity.score,
            metadata=dict(entity.metadata),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
