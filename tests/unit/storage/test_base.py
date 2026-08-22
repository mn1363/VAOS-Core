"""Unit tests for `src.storage.base`: the shared error hierarchy and entity (de)serialization
helpers every entity-persisting backend builds on.
"""

from uuid import UUID

import pytest
from src.core.exceptions import NotFoundError, VAOSError
from src.storage.base import (
    EntityNotFoundError,
    StorageConnectionError,
    StorageError,
    StorageIntegrityError,
    analysis_run_from_dict,
    analysis_run_to_dict,
    finding_from_dict,
    finding_to_dict,
    source_file_from_dict,
    source_file_to_dict,
    source_repository_from_dict,
    source_repository_to_dict,
)

from tests.unit.storage._fixtures import (
    make_analysis_run,
    make_finding,
    make_source_file,
    make_source_repository,
)

# --- Error hierarchy -----------------------------------------------------------------------


def test_storage_error_is_a_vaos_error() -> None:
    """`StorageError` should be a `VAOSError`, like every other VAOS exception."""
    assert issubclass(StorageError, VAOSError)


def test_storage_connection_error_is_a_storage_error() -> None:
    """`StorageConnectionError` should be a `StorageError`."""
    assert issubclass(StorageConnectionError, StorageError)


def test_storage_integrity_error_is_a_storage_error() -> None:
    """`StorageIntegrityError` should be a `StorageError`."""
    assert issubclass(StorageIntegrityError, StorageError)


def test_entity_not_found_error_is_a_not_found_error_not_a_storage_error() -> None:
    """`EntityNotFoundError` should be a `NotFoundError`, not a `StorageError` -- a missing
    entity is a `NotFoundError` regardless of which layer discovers it."""
    assert issubclass(EntityNotFoundError, NotFoundError)
    assert not issubclass(EntityNotFoundError, StorageError)


# --- SourceRepository ------------------------------------------------------------------------


def test_source_repository_round_trips_every_field() -> None:
    """`source_repository_to_dict` then `source_repository_from_dict` should reconstruct every
    field exactly, not just `id`."""
    original = make_source_repository()

    reconstructed = source_repository_from_dict(source_repository_to_dict(original))

    assert reconstructed.id == original.id
    assert reconstructed.created_at == original.created_at
    assert reconstructed.updated_at == original.updated_at
    assert reconstructed.name == original.name
    assert reconstructed.source_uri == original.source_uri
    assert reconstructed.provider == original.provider
    assert reconstructed.default_branch == original.default_branch
    assert reconstructed.status == original.status
    assert reconstructed.metadata == original.metadata


def test_source_repository_to_dict_is_json_safe() -> None:
    """Every value in the serialized dict should be a JSON-primitive type."""
    data = source_repository_to_dict(make_source_repository())

    assert isinstance(data["id"], str)
    assert isinstance(data["provider"], str)
    assert isinstance(data["status"], str)
    assert isinstance(data["created_at"], str)
    assert isinstance(data["updated_at"], str)
    assert isinstance(data["metadata"], dict)


def test_source_repository_from_dict_reraises_validation_error_on_corrupted_data() -> None:
    """Reconstructing from a dict with an invariant-violating field should raise, defensively
    against corrupted stored data."""
    data = source_repository_to_dict(make_source_repository())
    data["name"] = "   "

    with pytest.raises(Exception, match="name"):
        source_repository_from_dict(data)


# --- SourceFile -----------------------------------------------------------------------------


def test_source_file_round_trips_every_field() -> None:
    """`source_file_to_dict` then `source_file_from_dict` should reconstruct every field."""
    original = make_source_file()

    reconstructed = source_file_from_dict(source_file_to_dict(original))

    assert reconstructed.id == original.id
    assert reconstructed.created_at == original.created_at
    assert reconstructed.updated_at == original.updated_at
    assert reconstructed.repository_id == original.repository_id
    assert reconstructed.relative_path == original.relative_path
    assert reconstructed.language == original.language
    assert reconstructed.size_bytes == original.size_bytes
    assert reconstructed.metadata == original.metadata


def test_source_file_to_dict_stringifies_repository_id() -> None:
    """`repository_id`, a `UUID`, should serialize to its string form."""
    file = make_source_file()

    data = source_file_to_dict(file)

    assert data["repository_id"] == str(file.repository_id)
    assert isinstance(data["repository_id"], str)


# --- AnalysisRun -----------------------------------------------------------------------------


def test_analysis_run_round_trips_every_field() -> None:
    """`analysis_run_to_dict` then `analysis_run_from_dict` should reconstruct every field,
    including the optional `started_at`/`completed_at`/`error_message`."""
    original = make_analysis_run()

    reconstructed = analysis_run_from_dict(analysis_run_to_dict(original))

    assert reconstructed.id == original.id
    assert reconstructed.repository_id == original.repository_id
    assert reconstructed.status == original.status
    assert reconstructed.started_at == original.started_at
    assert reconstructed.completed_at == original.completed_at
    assert reconstructed.error_message == original.error_message


def test_analysis_run_round_trips_none_optional_fields() -> None:
    """A freshly-created, not-yet-started run has every optional field None -- these should
    round-trip as None, not as a stringified `"None"` or similar."""
    original = make_analysis_run(started_at=None, completed_at=None, error_message=None)

    data = analysis_run_to_dict(original)
    assert data["started_at"] is None
    assert data["completed_at"] is None
    assert data["error_message"] is None

    reconstructed = analysis_run_from_dict(data)
    assert reconstructed.started_at is None
    assert reconstructed.completed_at is None
    assert reconstructed.error_message is None


def test_analysis_run_round_trips_a_terminal_run_with_error_message() -> None:
    """A failed run's `completed_at` and `error_message` should round-trip too."""
    base = make_analysis_run()
    original = make_analysis_run(
        status="failed",
        completed_at=base.updated_at,
        error_message="clone failed: connection reset",
    )

    reconstructed = analysis_run_from_dict(analysis_run_to_dict(original))

    assert reconstructed.completed_at == original.completed_at
    assert reconstructed.error_message == original.error_message


# --- Finding ---------------------------------------------------------------------------------


def test_finding_round_trips_every_field() -> None:
    """`finding_to_dict` then `finding_from_dict` should reconstruct every field."""
    original = make_finding()

    reconstructed = finding_from_dict(finding_to_dict(original))

    assert reconstructed.id == original.id
    assert reconstructed.analysis_run_id == original.analysis_run_id
    assert reconstructed.category == original.category
    assert reconstructed.message == original.message
    assert reconstructed.source_file_id == original.source_file_id
    assert reconstructed.severity == original.severity
    assert reconstructed.score == original.score
    assert reconstructed.metadata == original.metadata


def test_finding_round_trips_none_source_file_id_and_score() -> None:
    """A repository-wide finding (no single file) has `source_file_id` and `score` both None."""
    original = make_finding(source_file_id=None, score=None)

    data = finding_to_dict(original)
    assert data["source_file_id"] is None
    assert data["score"] is None

    reconstructed = finding_from_dict(data)
    assert reconstructed.source_file_id is None
    assert reconstructed.score is None


def test_finding_to_dict_stringifies_source_file_id_when_present() -> None:
    """A present `source_file_id` should serialize to its string form, not stay a `UUID`."""
    finding = make_finding()

    data = finding_to_dict(finding)

    assert isinstance(data["source_file_id"], str)
    assert finding.source_file_id is not None
    assert UUID(data["source_file_id"]) == finding.source_file_id
