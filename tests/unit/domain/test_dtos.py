"""Unit tests for `src.domain.dtos`."""

import dataclasses
from uuid import uuid4

import pytest
from src.domain.dtos import AnalysisRunDTO, FindingDTO, SourceFileDTO, SourceRepositoryDTO
from src.domain.entities import (
    AnalysisRun,
    Finding,
    RepositoryProvider,
    SourceFile,
    SourceRepository,
)


def test_source_repository_dto_from_entity_matches_every_field() -> None:
    """`SourceRepositoryDTO.from_entity` should snapshot every field accurately."""
    entity = SourceRepository(
        name="vaos",
        source_uri="https://github.com/x/vaos",
        provider=RepositoryProvider.GITHUB,
        metadata={"stars": 42},
    )

    dto = SourceRepositoryDTO.from_entity(entity)

    assert dto.id == entity.id
    assert dto.name == entity.name
    assert dto.source_uri == entity.source_uri
    assert dto.provider == "github"
    assert dto.default_branch == entity.default_branch
    assert dto.status == "pending"
    assert dto.metadata == {"stars": 42}
    assert dto.created_at == entity.created_at
    assert dto.updated_at == entity.updated_at


def test_source_repository_dto_metadata_is_a_copy_not_an_alias() -> None:
    """Mutating the entity's metadata after snapshotting should not affect the DTO."""
    entity = SourceRepository(name="vaos", source_uri="uri", provider=RepositoryProvider.LOCAL)
    dto = SourceRepositoryDTO.from_entity(entity)

    entity.metadata["new_key"] = "new_value"

    assert "new_key" not in dto.metadata


def test_source_repository_dto_is_frozen() -> None:
    """A `SourceRepositoryDTO` should be immutable."""
    entity = SourceRepository(name="vaos", source_uri="uri", provider=RepositoryProvider.LOCAL)
    dto = SourceRepositoryDTO.from_entity(entity)

    with pytest.raises(dataclasses.FrozenInstanceError):
        dto.name = "changed"  # type: ignore[misc]


def test_source_file_dto_from_entity_matches_every_field() -> None:
    """`SourceFileDTO.from_entity` should snapshot every field accurately."""
    entity = SourceFile(repository_id=uuid4(), relative_path="src/main.py", size_bytes=128)

    dto = SourceFileDTO.from_entity(entity)

    assert dto.id == entity.id
    assert dto.repository_id == entity.repository_id
    assert dto.relative_path == "src/main.py"
    assert dto.language == "unknown"
    assert dto.size_bytes == 128


def test_analysis_run_dto_from_entity_includes_computed_duration() -> None:
    """`AnalysisRunDTO.from_entity` should include the entity's computed `duration_seconds`."""
    entity = AnalysisRun(repository_id=uuid4())
    entity.start()
    entity.complete()

    dto = AnalysisRunDTO.from_entity(entity)

    assert dto.status == "completed"
    assert dto.started_at == entity.started_at
    assert dto.completed_at == entity.completed_at
    assert dto.duration_seconds == entity.duration_seconds
    assert dto.duration_seconds is not None


def test_analysis_run_dto_from_entity_before_completion() -> None:
    """A DTO snapshot of a still-PENDING run should have null timing fields."""
    entity = AnalysisRun(repository_id=uuid4())

    dto = AnalysisRunDTO.from_entity(entity)

    assert dto.status == "pending"
    assert dto.started_at is None
    assert dto.duration_seconds is None
    assert dto.error_message is None


def test_finding_dto_from_entity_matches_every_field() -> None:
    """`FindingDTO.from_entity` should snapshot every field accurately."""
    run_id = uuid4()
    file_id = uuid4()
    entity = Finding(
        analysis_run_id=run_id,
        source_file_id=file_id,
        category="security",
        message="hardcoded secret",
        score=2.5,
        metadata={"line": 10},
    )

    dto = FindingDTO.from_entity(entity)

    assert dto.id == entity.id
    assert dto.analysis_run_id == run_id
    assert dto.source_file_id == file_id
    assert dto.category == "security"
    assert dto.severity == "info"
    assert dto.message == "hardcoded secret"
    assert dto.score == 2.5
    assert dto.metadata == {"line": 10}


def test_finding_dto_from_entity_with_no_source_file() -> None:
    """A finding not scoped to a specific file should snapshot `source_file_id` as None."""
    entity = Finding(analysis_run_id=uuid4(), category="architecture", message="layering issue")

    dto = FindingDTO.from_entity(entity)

    assert dto.source_file_id is None
