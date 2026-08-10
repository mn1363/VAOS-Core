"""Unit tests for `src.analyzers.dependency.base`."""

import pytest
from src.analyzers.dependency.base import (
    DependencyAnalysisResult,
    DependencyAnalyzer,
    DependencyProfile,
    require_successful_extraction,
    summarize_external_targets,
)
from src.core.exceptions import ValidationError
from src.extractors.imports.base import DependencyEdge, ImportExtractionResult


def _successful_extraction(relative_path: str = "a.py") -> ImportExtractionResult:
    """Build a minimal, successful `ImportExtractionResult` for use in analysis tests."""
    return ImportExtractionResult.ok(relative_path=relative_path, edges=())


def _failed_extraction(relative_path: str = "a.py") -> ImportExtractionResult:
    """Build a minimal, failed `ImportExtractionResult` for use in analysis tests."""
    return ImportExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_dependency_analyzer_cannot_be_instantiated_directly() -> None:
    """The abstract `DependencyAnalyzer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        DependencyAnalyzer()  # type: ignore[abstract]


def test_dependency_analysis_result_ok_builds_a_successful_result() -> None:
    """`DependencyAnalysisResult.ok` should set `succeeded=True` and carry the profile."""
    profile = DependencyProfile(relative_path="a.py")

    result = DependencyAnalysisResult.ok(relative_path="a.py", profile=profile)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.profile == profile
    assert result.error_message is None


def test_dependency_analysis_result_failed_builds_a_failed_result() -> None:
    """`DependencyAnalysisResult.failed` should set `succeeded=False` and carry the error."""
    result = DependencyAnalysisResult.failed(relative_path="a.py", error_message="no data")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.profile is None
    assert result.error_message == "no data"


def test_dependency_analysis_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    profile = DependencyProfile(relative_path="a.py")
    with pytest.raises(ValidationError):
        DependencyAnalysisResult(
            relative_path="a.py", succeeded=True, profile=profile, error_message="unexpected"
        )


def test_dependency_analysis_result_requires_profile_on_success() -> None:
    """Constructing a successful result without a profile should raise."""
    with pytest.raises(ValidationError):
        DependencyAnalysisResult(relative_path="a.py", succeeded=True, profile=None)


def test_dependency_analysis_result_rejects_profile_on_failure() -> None:
    """Constructing a failed result with a profile attached should raise."""
    profile = DependencyProfile(relative_path="a.py")
    with pytest.raises(ValidationError):
        DependencyAnalysisResult(
            relative_path="a.py", succeeded=False, profile=profile, error_message="bad"
        )


def test_dependency_analysis_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        DependencyAnalysisResult(relative_path="a.py", succeeded=False)


def test_require_successful_extraction_returns_a_successful_result_unchanged() -> None:
    """`require_successful_extraction` should pass a successful result through unchanged."""
    extraction_result = _successful_extraction()
    assert require_successful_extraction(extraction_result) is extraction_result


def test_require_successful_extraction_rejects_a_failed_result() -> None:
    """`require_successful_extraction` should raise `ValidationError` for a failed result."""
    with pytest.raises(ValidationError):
        require_successful_extraction(_failed_extraction())


def test_dependency_profile_is_frozen() -> None:
    """`DependencyProfile` should be immutable once constructed."""
    profile = DependencyProfile(relative_path="a.py")
    with pytest.raises(AttributeError):
        profile.relative_path = "b.py"  # type: ignore[misc]


def test_dependency_profile_defaults() -> None:
    """`DependencyProfile` should default every count and the target tuple sensibly."""
    profile = DependencyProfile(relative_path="a.py")
    assert profile.total_dependency_count == 0
    assert profile.internal_dependency_count == 0
    assert profile.external_dependency_count == 0
    assert profile.external_targets == ()


def test_dependency_profile_accepts_a_consistent_breakdown() -> None:
    """A profile whose internal/external counts sum to the total should construct cleanly."""
    profile = DependencyProfile(
        relative_path="a.py",
        total_dependency_count=3,
        internal_dependency_count=1,
        external_dependency_count=2,
        external_targets=("os", "sys"),
    )
    assert profile.total_dependency_count == 3
    assert profile.external_targets == ("os", "sys")


def test_dependency_profile_rejects_negative_counts() -> None:
    """Constructing a profile with a negative count should raise."""
    with pytest.raises(ValidationError):
        DependencyProfile(relative_path="a.py", total_dependency_count=-1)


def test_dependency_profile_rejects_inconsistent_totals() -> None:
    """Constructing a profile whose breakdown does not sum to the total should raise."""
    with pytest.raises(ValidationError):
        DependencyProfile(
            relative_path="a.py",
            total_dependency_count=5,
            internal_dependency_count=1,
            external_dependency_count=1,
        )


def test_dependency_profile_rejects_unsorted_external_targets() -> None:
    """Constructing a profile with unsorted external targets should raise."""
    with pytest.raises(ValidationError):
        DependencyProfile(relative_path="a.py", external_targets=("sys", "os"))


def test_dependency_profile_rejects_duplicate_external_targets() -> None:
    """Constructing a profile with duplicate external targets should raise."""
    with pytest.raises(ValidationError):
        DependencyProfile(relative_path="a.py", external_targets=("os", "os"))


def test_summarize_external_targets_dedupes_and_sorts() -> None:
    """`summarize_external_targets` should deduplicate and sort external target modules."""
    edges = (
        DependencyEdge(source_path="a.py", target_module="sys", is_internal=False),
        DependencyEdge(source_path="a.py", target_module="os", is_internal=False),
        DependencyEdge(source_path="a.py", target_module="os", is_internal=False),
    )
    assert summarize_external_targets(edges) == ("os", "sys")


def test_summarize_external_targets_excludes_internal_edges() -> None:
    """`summarize_external_targets` should exclude edges classified as internal."""
    edges = (
        DependencyEdge(source_path="a.py", target_module=".sibling", is_internal=True),
        DependencyEdge(source_path="a.py", target_module="os", is_internal=False),
    )
    assert summarize_external_targets(edges) == ("os",)


def test_summarize_external_targets_handles_no_edges() -> None:
    """`summarize_external_targets` should return an empty tuple for no edges."""
    assert summarize_external_targets(()) == ()
