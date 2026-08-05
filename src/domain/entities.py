"""Domain entities: the core business objects of VAOS.

Entities are identified by a stable UUID and have a lifecycle -- their
status can change over time -- so, unlike the flat, immutable DTOs in
`dtos.py`, entities are deliberately NOT frozen dataclasses. Every
subclass of `Entity` is declared `@dataclass(eq=False, kw_only=True)`:
`eq=False` so it inherits `Entity`'s identity-based equality instead of
generating a field-by-field one, and `kw_only=True` so inherited and
subclass-defined fields can mix freely regardless of which ones carry
defaults.

State-transition methods validate their own invariants and raise
`core.exceptions.ValidationError` on an illegal transition -- `domain`'s
only allowed dependency is on `core`, the innermost layer.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any
from uuid import UUID, uuid4

from src.core.exceptions import ValidationError


class RepositoryProvider(StrEnum):
    """Where a `SourceRepository` was collected from.

    Mirrors the frozen `collectors/{filesystem,github,gitlab,local}`
    subpackages one-for-one.
    """

    FILESYSTEM = auto()
    GITHUB = auto()
    GITLAB = auto()
    LOCAL = auto()


class RepositoryStatus(StrEnum):
    """Lifecycle status of a `SourceRepository`."""

    PENDING = auto()
    COLLECTING = auto()
    READY = auto()
    FAILED = auto()


class SourceLanguage(StrEnum):
    """Programming language of a `SourceFile`.

    Mirrors the frozen `parsers/{python,rust,cpp,go,typescript,
    javascript,java,csharp,php}` subpackages one-for-one, plus `UNKNOWN`
    for files no parser claims.
    """

    PYTHON = auto()
    RUST = auto()
    CPP = auto()
    GO = auto()
    TYPESCRIPT = auto()
    JAVASCRIPT = auto()
    JAVA = auto()
    CSHARP = auto()
    PHP = auto()
    UNKNOWN = auto()


class AnalysisRunStatus(StrEnum):
    """Lifecycle status of an `AnalysisRun`."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class FindingSeverity(StrEnum):
    """Severity of a single `Finding`."""

    INFO = auto()
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()


@dataclass(kw_only=True)
class Entity:
    """Base class for domain entities identified by a stable UUID.

    Two entities are considered equal when their `id` fields match,
    regardless of any other attribute -- standard DDD entity semantics, as
    opposed to the value-based equality of a plain dataclass. Subclasses
    must be declared `@dataclass(eq=False, kw_only=True)` so this identity
    based equality is inherited rather than overwritten by a generated,
    field-by-field `__eq__`.

    Attributes:
        id: Stable, globally unique identifier for this entity.
        created_at: Timestamp at which the entity was first created.
        updated_at: Timestamp at which the entity was last modified.
    """

    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __eq__(self, other: object) -> bool:
        """Compare entities by identity rather than by attribute values.

        Args:
            other: The object to compare against.

        Returns:
            True if `other` is an `Entity` with the same `id`.
        """
        if not isinstance(other, Entity):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash the entity using its identity, matching `__eq__` semantics.

        Returns:
            Hash of the entity's `id`.
        """
        return hash(self.id)

    def touch(self) -> None:
        """Refresh `updated_at` to the current UTC time.

        Called by state-transition methods on subclasses so `updated_at`
        reflects the most recent modification.
        """
        self.updated_at = datetime.now(UTC)


@dataclass(eq=False, kw_only=True)
class SourceRepository(Entity):
    """A source-code repository collected for analysis.

    Attributes:
        name: Human-readable name of the repository.
        source_uri: Location the repository was (or will be) collected
            from, e.g. a filesystem path or a GitHub URL.
        provider: Where the repository was collected from.
        default_branch: Default branch to analyze, when relevant.
        status: Current lifecycle status of the repository.
        metadata: Freeform, structured metadata describing the repository.
    """

    name: str
    source_uri: str
    provider: RepositoryProvider
    default_branch: str = "main"
    status: RepositoryStatus = RepositoryStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate construction-time invariants.

        Raises:
            ValidationError: If `name` or `source_uri` is blank.
        """
        if not self.name.strip():
            raise ValidationError("SourceRepository.name must not be empty")
        if not self.source_uri.strip():
            raise ValidationError("SourceRepository.source_uri must not be empty")

    def mark_collecting(self) -> None:
        """Transition from PENDING to COLLECTING.

        Raises:
            ValidationError: If the repository is not currently PENDING.
        """
        if self.status is not RepositoryStatus.PENDING:
            raise ValidationError(
                f"cannot start collecting a repository in status '{self.status}'",
                details={"repository_id": str(self.id), "status": str(self.status)},
            )
        self.status = RepositoryStatus.COLLECTING
        self.touch()

    def mark_ready(self) -> None:
        """Transition from COLLECTING to READY.

        Raises:
            ValidationError: If the repository is not currently COLLECTING.
        """
        if self.status is not RepositoryStatus.COLLECTING:
            raise ValidationError(
                f"cannot mark ready a repository in status '{self.status}'",
                details={"repository_id": str(self.id), "status": str(self.status)},
            )
        self.status = RepositoryStatus.READY
        self.touch()

    def mark_failed(self, reason: str) -> None:
        """Transition from PENDING or COLLECTING to FAILED.

        Args:
            reason: Human-readable explanation of the failure, stored in
                `metadata["failure_reason"]`.

        Raises:
            ValidationError: If the repository is already READY or FAILED.
        """
        if self.status not in (RepositoryStatus.PENDING, RepositoryStatus.COLLECTING):
            raise ValidationError(
                f"cannot fail a repository in status '{self.status}'",
                details={"repository_id": str(self.id), "status": str(self.status)},
            )
        self.status = RepositoryStatus.FAILED
        self.metadata = {**self.metadata, "failure_reason": reason}
        self.touch()


@dataclass(eq=False, kw_only=True)
class SourceFile(Entity):
    """A single file within a `SourceRepository`.

    Attributes:
        repository_id: Identifier of the owning `SourceRepository`.
        relative_path: Path of the file relative to the repository root.
        language: Programming language of the file, if recognized.
        size_bytes: Size of the file, in bytes.
        metadata: Freeform, structured metadata describing the file.
    """

    repository_id: UUID
    relative_path: str
    language: SourceLanguage = SourceLanguage.UNKNOWN
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate construction-time invariants.

        Raises:
            ValidationError: If `relative_path` is blank or `size_bytes`
                is negative.
        """
        if not self.relative_path.strip():
            raise ValidationError("SourceFile.relative_path must not be empty")
        if self.size_bytes < 0:
            raise ValidationError("SourceFile.size_bytes must not be negative")


@dataclass(eq=False, kw_only=True)
class AnalysisRun(Entity):
    """A single execution of the analysis pipeline against a repository.

    Attributes:
        repository_id: Identifier of the `SourceRepository` being analyzed.
        status: Current lifecycle status of the run.
        started_at: Timestamp the run transitioned to RUNNING, if it has.
        completed_at: Timestamp the run reached a terminal status, if it
            has.
        error_message: Explanation of the failure, set when the run fails.
    """

    repository_id: UUID
    status: AnalysisRunStatus = AnalysisRunStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    def start(self) -> None:
        """Transition from PENDING to RUNNING.

        Raises:
            ValidationError: If the run is not currently PENDING.
        """
        if self.status is not AnalysisRunStatus.PENDING:
            raise ValidationError(
                f"cannot start an analysis run in status '{self.status}'",
                details={"run_id": str(self.id), "status": str(self.status)},
            )
        self.status = AnalysisRunStatus.RUNNING
        self.started_at = datetime.now(UTC)
        self.touch()

    def complete(self) -> None:
        """Transition from RUNNING to COMPLETED.

        Raises:
            ValidationError: If the run is not currently RUNNING.
        """
        if self.status is not AnalysisRunStatus.RUNNING:
            raise ValidationError(
                f"cannot complete an analysis run in status '{self.status}'",
                details={"run_id": str(self.id), "status": str(self.status)},
            )
        self.status = AnalysisRunStatus.COMPLETED
        self.completed_at = datetime.now(UTC)
        self.touch()

    def fail(self, reason: str) -> None:
        """Transition from PENDING or RUNNING to FAILED.

        Args:
            reason: Human-readable explanation of the failure, stored in
                `error_message`.

        Raises:
            ValidationError: If the run has already reached a terminal
                status.
        """
        if self.status not in (AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING):
            raise ValidationError(
                f"cannot fail an analysis run in status '{self.status}'",
                details={"run_id": str(self.id), "status": str(self.status)},
            )
        self.status = AnalysisRunStatus.FAILED
        self.completed_at = datetime.now(UTC)
        self.error_message = reason
        self.touch()

    def cancel(self) -> None:
        """Transition from PENDING or RUNNING to CANCELLED.

        Raises:
            ValidationError: If the run has already reached a terminal
                status.
        """
        if self.status not in (AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING):
            raise ValidationError(
                f"cannot cancel an analysis run in status '{self.status}'",
                details={"run_id": str(self.id), "status": str(self.status)},
            )
        self.status = AnalysisRunStatus.CANCELLED
        self.completed_at = datetime.now(UTC)
        self.touch()

    @property
    def duration_seconds(self) -> float | None:
        """Elapsed time between `started_at` and `completed_at`.

        Returns:
            The elapsed duration in seconds, or None if the run has not
            both started and reached a terminal status.
        """
        if self.started_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()


@dataclass(eq=False, kw_only=True)
class Finding(Entity):
    """A single observation produced during analysis of a repository.

    `Finding` is intentionally generic: it is the shared result shape for
    whichever future extractor, analyzer, or scorer produced it --
    `category` is a freeform label (e.g. `"security"`, `"complexity"`,
    `"architecture"`) rather than a fixed enum, since the exact taxonomy
    belongs to those not-yet-built layers, not to `domain`.

    Attributes:
        analysis_run_id: Identifier of the owning `AnalysisRun`.
        category: Freeform label for the kind of finding this is.
        message: Human-readable description of the finding.
        source_file_id: Identifier of the specific `SourceFile` this
            finding is about, if it is about one file in particular.
        severity: Severity of the finding.
        score: Optional numeric score associated with the finding.
        metadata: Freeform, structured metadata about the finding.
    """

    analysis_run_id: UUID
    category: str
    message: str
    source_file_id: UUID | None = None
    severity: FindingSeverity = FindingSeverity.INFO
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate construction-time invariants.

        Raises:
            ValidationError: If `category` or `message` is blank.
        """
        if not self.category.strip():
            raise ValidationError("Finding.category must not be empty")
        if not self.message.strip():
            raise ValidationError("Finding.message must not be empty")
