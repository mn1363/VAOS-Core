"""Shared entity fixture builders reused across `tests/unit/storage/*`.

Not a test file itself -- imported by `test_base.py` and each backend's own `test_driver.py` so
every test builds entities the same way, with the same field values, for easy cross-comparison.
"""

from datetime import UTC, datetime
from uuid import UUID

from src.domain.entities import (
    AnalysisRun,
    AnalysisRunStatus,
    Finding,
    FindingSeverity,
    RepositoryProvider,
    RepositoryStatus,
    SourceFile,
    SourceLanguage,
    SourceRepository,
)

REPOSITORY_ID = UUID("11111111-1111-1111-1111-111111111111")
FILE_ID = UUID("22222222-2222-2222-2222-222222222222")
RUN_ID = UUID("33333333-3333-3333-3333-333333333333")
FINDING_ID = UUID("44444444-4444-4444-4444-444444444444")
CREATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
UPDATED_AT = datetime(2026, 1, 2, 8, 30, 0, tzinfo=UTC)


def make_source_repository(**overrides: object) -> SourceRepository:
    """Build a fully-populated `SourceRepository`, every field non-default where possible."""
    fields: dict[str, object] = {
        "id": REPOSITORY_ID,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "name": "vaos-core",
        "source_uri": "https://github.com/example/vaos-core",
        "provider": RepositoryProvider.GITHUB,
        "default_branch": "develop",
        "status": RepositoryStatus.COLLECTING,
        "metadata": {"stars": 42, "nested": {"a": 1}},
    }
    fields.update(overrides)
    return SourceRepository(**fields)  # type: ignore[arg-type]


def make_source_file(**overrides: object) -> SourceFile:
    """Build a fully-populated `SourceFile`, every field non-default where possible."""
    fields: dict[str, object] = {
        "id": FILE_ID,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "repository_id": REPOSITORY_ID,
        "relative_path": "src/main.py",
        "language": SourceLanguage.PYTHON,
        "size_bytes": 1024,
        "metadata": {"line_count": 40},
    }
    fields.update(overrides)
    return SourceFile(**fields)  # type: ignore[arg-type]


def make_analysis_run(**overrides: object) -> AnalysisRun:
    """Build a fully-populated `AnalysisRun`, including optional fields, by default."""
    fields: dict[str, object] = {
        "id": RUN_ID,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "repository_id": REPOSITORY_ID,
        "status": AnalysisRunStatus.RUNNING,
        "started_at": CREATED_AT,
        "completed_at": None,
        "error_message": None,
    }
    fields.update(overrides)
    return AnalysisRun(**fields)  # type: ignore[arg-type]


def make_finding(**overrides: object) -> Finding:
    """Build a fully-populated `Finding`, every field non-default where possible."""
    fields: dict[str, object] = {
        "id": FINDING_ID,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "analysis_run_id": RUN_ID,
        "category": "complexity",
        "message": "Function exceeds recommended cyclomatic complexity",
        "source_file_id": FILE_ID,
        "severity": FindingSeverity.HIGH,
        "score": 0.87,
        "metadata": {"function": "parse_tree"},
    }
    fields.update(overrides)
    return Finding(**fields)  # type: ignore[arg-type]
