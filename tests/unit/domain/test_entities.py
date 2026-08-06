"""Unit tests for `src.domain.entities`."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import (
    AnalysisRun,
    AnalysisRunStatus,
    Entity,
    Finding,
    FindingSeverity,
    RepositoryProvider,
    RepositoryStatus,
    SourceFile,
    SourceLanguage,
    SourceRepository,
)

# --- Entity (base) ---


def test_entity_generates_a_unique_id_and_timestamps_by_default() -> None:
    """A bare `Entity` should get a random id and UTC-aware timestamps."""
    entity = Entity()

    assert isinstance(entity.id, UUID)
    assert entity.created_at.tzinfo is not None
    assert entity.updated_at.tzinfo is not None


def test_entity_equality_is_identity_based() -> None:
    """Two entities are equal only when their `id` matches, not by field values."""
    shared_id = uuid4()
    first = Entity(id=shared_id)
    second = Entity(id=shared_id, created_at=datetime.now(UTC))

    assert first == second
    assert hash(first) == hash(second)
    assert first != Entity()


def test_entity_is_not_equal_to_a_non_entity() -> None:
    """Comparing an `Entity` to an unrelated object should not raise or match."""
    assert Entity() != "not an entity"


def test_entity_touch_refreshes_updated_at_without_changing_identity() -> None:
    """`touch()` should advance `updated_at` without changing `created_at` or `id`."""
    old_timestamp = datetime(2020, 1, 1, tzinfo=UTC)
    entity = Entity(updated_at=old_timestamp)
    original_id, original_created = entity.id, entity.created_at

    entity.touch()

    assert entity.id == original_id
    assert entity.created_at == original_created
    assert entity.updated_at > old_timestamp


# --- SourceRepository ---


def test_source_repository_defaults() -> None:
    """A `SourceRepository` should default to PENDING, branch 'main', empty metadata."""
    repo = SourceRepository(
        name="vaos", source_uri="https://github.com/x/vaos", provider=RepositoryProvider.GITHUB
    )

    assert repo.status is RepositoryStatus.PENDING
    assert repo.default_branch == "main"
    assert repo.metadata == {}


def test_source_repository_rejects_blank_name() -> None:
    """An empty or whitespace-only `name` should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        SourceRepository(name="  ", source_uri="uri", provider=RepositoryProvider.LOCAL)


def test_source_repository_rejects_blank_source_uri() -> None:
    """An empty or whitespace-only `source_uri` should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        SourceRepository(name="vaos", source_uri="  ", provider=RepositoryProvider.LOCAL)


def test_source_repository_lifecycle_happy_path() -> None:
    """PENDING -> COLLECTING -> READY should succeed and bump `updated_at`."""
    repo = SourceRepository(name="vaos", source_uri="uri", provider=RepositoryProvider.LOCAL)
    before = repo.updated_at

    repo.mark_collecting()
    status_after_collecting = repo.status
    assert status_after_collecting is RepositoryStatus.COLLECTING
    assert repo.updated_at >= before

    repo.mark_ready()
    status_after_ready = repo.status
    assert status_after_ready is RepositoryStatus.READY


def test_source_repository_mark_collecting_requires_pending() -> None:
    """`mark_collecting` should reject any status other than PENDING."""
    repo = SourceRepository(name="vaos", source_uri="uri", provider=RepositoryProvider.LOCAL)
    repo.mark_collecting()

    with pytest.raises(ValidationError):
        repo.mark_collecting()


def test_source_repository_mark_ready_requires_collecting() -> None:
    """`mark_ready` should reject any status other than COLLECTING."""
    repo = SourceRepository(name="vaos", source_uri="uri", provider=RepositoryProvider.LOCAL)

    with pytest.raises(ValidationError):
        repo.mark_ready()


def test_source_repository_mark_failed_from_pending_or_collecting() -> None:
    """`mark_failed` should succeed from PENDING or COLLECTING and record the reason."""
    repo = SourceRepository(name="vaos", source_uri="uri", provider=RepositoryProvider.LOCAL)

    repo.mark_failed("network error")

    assert repo.status is RepositoryStatus.FAILED
    assert repo.metadata["failure_reason"] == "network error"


def test_source_repository_mark_failed_rejects_ready() -> None:
    """`mark_failed` should reject a repository that is already READY."""
    repo = SourceRepository(name="vaos", source_uri="uri", provider=RepositoryProvider.LOCAL)
    repo.mark_collecting()
    repo.mark_ready()

    with pytest.raises(ValidationError):
        repo.mark_failed("too late")


# --- SourceFile ---


def test_source_file_defaults() -> None:
    """A `SourceFile` should default to UNKNOWN language, zero size, empty metadata."""
    file = SourceFile(repository_id=uuid4(), relative_path="src/main.py")

    assert file.language is SourceLanguage.UNKNOWN
    assert file.size_bytes == 0
    assert file.metadata == {}


def test_source_file_rejects_blank_relative_path() -> None:
    """An empty or whitespace-only `relative_path` should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        SourceFile(repository_id=uuid4(), relative_path=" ")


def test_source_file_rejects_negative_size() -> None:
    """A negative `size_bytes` should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        SourceFile(repository_id=uuid4(), relative_path="a.py", size_bytes=-1)


# --- AnalysisRun ---


def test_analysis_run_defaults() -> None:
    """A fresh `AnalysisRun` should be PENDING with no timestamps or error set."""
    run = AnalysisRun(repository_id=uuid4())

    assert run.status is AnalysisRunStatus.PENDING
    assert run.started_at is None
    assert run.completed_at is None
    assert run.error_message is None
    assert run.duration_seconds is None


def test_analysis_run_start_then_complete() -> None:
    """PENDING -> RUNNING -> COMPLETED should succeed and compute a duration."""
    run = AnalysisRun(repository_id=uuid4())

    run.start()
    status_after_start = run.status
    assert status_after_start is AnalysisRunStatus.RUNNING
    assert run.started_at is not None

    run.complete()
    status_after_complete = run.status
    assert status_after_complete is AnalysisRunStatus.COMPLETED
    assert run.completed_at is not None
    assert run.duration_seconds is not None
    assert run.duration_seconds >= 0


def test_analysis_run_start_requires_pending() -> None:
    """`start()` should reject any status other than PENDING."""
    run = AnalysisRun(repository_id=uuid4())
    run.start()

    with pytest.raises(ValidationError):
        run.start()


def test_analysis_run_complete_requires_running() -> None:
    """`complete()` should reject any status other than RUNNING."""
    run = AnalysisRun(repository_id=uuid4())

    with pytest.raises(ValidationError):
        run.complete()


def test_analysis_run_fail_from_pending() -> None:
    """`fail()` should succeed from PENDING and record `error_message`."""
    run = AnalysisRun(repository_id=uuid4())

    run.fail("collector crashed")

    assert run.status is AnalysisRunStatus.FAILED
    assert run.error_message == "collector crashed"
    assert run.completed_at is not None


def test_analysis_run_fail_from_running() -> None:
    """`fail()` should succeed from RUNNING."""
    run = AnalysisRun(repository_id=uuid4())
    run.start()

    run.fail("parser crashed")

    assert run.status is AnalysisRunStatus.FAILED


def test_analysis_run_fail_requires_non_terminal_status() -> None:
    """`fail()` should reject a run that already reached a terminal status."""
    run = AnalysisRun(repository_id=uuid4())
    run.start()
    run.complete()

    with pytest.raises(ValidationError):
        run.fail("too late")


def test_analysis_run_cancel_from_pending_or_running() -> None:
    """`cancel()` should succeed from PENDING or RUNNING."""
    run = AnalysisRun(repository_id=uuid4())

    run.cancel()

    assert run.status is AnalysisRunStatus.CANCELLED
    assert run.completed_at is not None


def test_analysis_run_cancel_requires_non_terminal_status() -> None:
    """`cancel()` should reject a run that already reached a terminal status."""
    run = AnalysisRun(repository_id=uuid4())
    run.start()
    run.complete()

    with pytest.raises(ValidationError):
        run.cancel()


# --- Finding ---


def test_finding_defaults() -> None:
    """A `Finding` should default to INFO severity, no score, empty metadata."""
    finding = Finding(analysis_run_id=uuid4(), category="quality", message="looks fine")

    assert finding.severity is FindingSeverity.INFO
    assert finding.source_file_id is None
    assert finding.score is None
    assert finding.metadata == {}


def test_finding_rejects_blank_category() -> None:
    """An empty or whitespace-only `category` should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        Finding(analysis_run_id=uuid4(), category=" ", message="x")


def test_finding_rejects_blank_message() -> None:
    """An empty or whitespace-only `message` should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        Finding(analysis_run_id=uuid4(), category="quality", message=" ")


# --- Enums ---


def test_repository_provider_values_match_the_frozen_collectors_subpackages() -> None:
    """`RepositoryProvider` members should mirror `collectors/{filesystem,github,gitlab,local}`."""
    assert {p.value for p in RepositoryProvider} == {"filesystem", "github", "gitlab", "local"}


def test_source_language_values_match_the_frozen_parsers_subpackages() -> None:
    """`SourceLanguage` members should mirror the frozen `parsers/` subpackages, plus UNKNOWN."""
    assert {lang.value for lang in SourceLanguage} == {
        "python",
        "rust",
        "cpp",
        "go",
        "typescript",
        "javascript",
        "java",
        "csharp",
        "php",
        "unknown",
    }


def test_analysis_run_status_and_finding_severity_have_expected_members() -> None:
    """`AnalysisRunStatus` and `FindingSeverity` should expose their documented members."""
    assert {s.value for s in AnalysisRunStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    }
    assert {s.value for s in FindingSeverity} == {"info", "low", "medium", "high", "critical"}
