"""Unit tests for `src.collectors.base`."""

import pytest
from src.collectors.base import CollectionResult, Collector, require_source, strip_git_suffix
from src.core.exceptions import ValidationError
from src.domain.entities import RepositoryProvider, SourceRepository


def _repository() -> SourceRepository:
    """Build a minimal, valid `SourceRepository` for use in result-construction tests."""
    return SourceRepository(
        name="example",
        source_uri="/tmp/example",
        provider=RepositoryProvider.FILESYSTEM,
    )


def test_collector_cannot_be_instantiated_directly() -> None:
    """The abstract `Collector` Port must not be instantiable."""
    with pytest.raises(TypeError):
        Collector()  # type: ignore[abstract]


def test_collection_result_ok_builds_a_successful_result() -> None:
    """`CollectionResult.ok` should set `succeeded=True` and carry the given repositories."""
    repository = _repository()

    result = CollectionResult.ok("source", [repository])

    assert result.succeeded is True
    assert result.source == "source"
    assert result.repositories == (repository,)
    assert result.error_message is None


def test_collection_result_ok_defaults_to_no_repositories() -> None:
    """`CollectionResult.ok` should accept an empty sequence for a source with no findings."""
    result = CollectionResult.ok("source", [])

    assert result.succeeded is True
    assert result.repositories == ()


def test_collection_result_failed_builds_a_failed_result() -> None:
    """`CollectionResult.failed` should set `succeeded=False` and carry the error message."""
    result = CollectionResult.failed("source", "went wrong")

    assert result.succeeded is False
    assert result.source == "source"
    assert result.repositories == ()
    assert result.error_message == "went wrong"


def test_collection_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    with pytest.raises(ValidationError):
        CollectionResult(source="s", succeeded=True, error_message="unexpected")


def test_collection_result_rejects_repositories_on_failure() -> None:
    """Constructing a failed result with repositories attached should raise."""
    with pytest.raises(ValidationError):
        CollectionResult(
            source="s",
            succeeded=False,
            repositories=(_repository(),),
            error_message="went wrong",
        )


def test_collection_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        CollectionResult(source="s", succeeded=False)


def test_require_source_returns_a_non_blank_value_unchanged() -> None:
    """`require_source` should pass a non-blank string through unchanged."""
    assert require_source("a-value") == "a-value"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_require_source_rejects_blank_values(blank: str) -> None:
    """`require_source` should raise `ValidationError` for empty or whitespace-only input."""
    with pytest.raises(ValidationError):
        require_source(blank)


def test_strip_git_suffix_removes_trailing_dot_git() -> None:
    """`strip_git_suffix` should remove exactly one trailing `.git`."""
    assert strip_git_suffix("owner/repo.git") == "owner/repo"


def test_strip_git_suffix_leaves_other_strings_unchanged() -> None:
    """`strip_git_suffix` should not modify a reference that has no `.git` suffix."""
    assert strip_git_suffix("owner/repo") == "owner/repo"
