"""Unit tests for `src.analyzers.documentation.base`."""

import pytest
from src.analyzers.documentation.base import (
    DocumentationAnalysisResult,
    DocumentationAnalyzer,
    DocumentationCoverage,
    coverage_ratio,
    require_successful_extraction,
)
from src.core.exceptions import ValidationError
from src.extractors.ast.base import AstExtractionResult, AstMetadata


def _successful_extraction(relative_path: str = "a.py") -> AstExtractionResult:
    """Build a minimal, successful `AstExtractionResult` for use in analysis tests."""
    metadata = AstMetadata(relative_path=relative_path)
    return AstExtractionResult.ok(relative_path=relative_path, metadata=metadata)


def _failed_extraction(relative_path: str = "a.py") -> AstExtractionResult:
    """Build a minimal, failed `AstExtractionResult` for use in analysis tests."""
    return AstExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_documentation_analyzer_cannot_be_instantiated_directly() -> None:
    """The abstract `DocumentationAnalyzer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        DocumentationAnalyzer()  # type: ignore[abstract]


def test_documentation_analysis_result_ok_builds_a_successful_result() -> None:
    """`DocumentationAnalysisResult.ok` should set `succeeded=True` and carry the coverage."""
    coverage = DocumentationCoverage(relative_path="a.py")

    result = DocumentationAnalysisResult.ok(relative_path="a.py", coverage=coverage)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.coverage == coverage
    assert result.error_message is None


def test_documentation_analysis_result_failed_builds_a_failed_result() -> None:
    """`DocumentationAnalysisResult.failed` should set `succeeded=False` and carry the error."""
    result = DocumentationAnalysisResult.failed(relative_path="a.py", error_message="no data")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.coverage is None
    assert result.error_message == "no data"


def test_documentation_analysis_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    coverage = DocumentationCoverage(relative_path="a.py")
    with pytest.raises(ValidationError):
        DocumentationAnalysisResult(
            relative_path="a.py", succeeded=True, coverage=coverage, error_message="unexpected"
        )


def test_documentation_analysis_result_requires_coverage_on_success() -> None:
    """Constructing a successful result without coverage should raise."""
    with pytest.raises(ValidationError):
        DocumentationAnalysisResult(relative_path="a.py", succeeded=True, coverage=None)


def test_documentation_analysis_result_rejects_coverage_on_failure() -> None:
    """Constructing a failed result with coverage attached should raise."""
    coverage = DocumentationCoverage(relative_path="a.py")
    with pytest.raises(ValidationError):
        DocumentationAnalysisResult(
            relative_path="a.py", succeeded=False, coverage=coverage, error_message="bad"
        )


def test_documentation_analysis_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        DocumentationAnalysisResult(relative_path="a.py", succeeded=False)


def test_require_successful_extraction_returns_a_successful_result_unchanged() -> None:
    """`require_successful_extraction` should pass a successful result through unchanged."""
    extraction_result = _successful_extraction()
    assert require_successful_extraction(extraction_result) is extraction_result


def test_require_successful_extraction_rejects_a_failed_result() -> None:
    """`require_successful_extraction` should raise `ValidationError` for a failed result."""
    with pytest.raises(ValidationError):
        require_successful_extraction(_failed_extraction())


def test_documentation_coverage_is_frozen() -> None:
    """`DocumentationCoverage` should be immutable once constructed."""
    coverage = DocumentationCoverage(relative_path="a.py")
    with pytest.raises(AttributeError):
        coverage.relative_path = "b.py"  # type: ignore[misc]


def test_documentation_coverage_defaults_to_vacuously_fully_covered() -> None:
    """`DocumentationCoverage` should default every ratio to `1.0` for an empty file."""
    coverage = DocumentationCoverage(relative_path="a.py")
    assert coverage.class_documentation_ratio == 1.0
    assert coverage.function_documentation_ratio == 1.0
    assert coverage.overall_documentation_ratio == 1.0
    assert coverage.class_count == 0
    assert coverage.function_count == 0


def test_documentation_coverage_rejects_negative_counts() -> None:
    """Constructing coverage with a negative count should raise."""
    with pytest.raises(ValidationError):
        DocumentationCoverage(relative_path="a.py", class_count=-1)


def test_documentation_coverage_rejects_documented_exceeding_total() -> None:
    """Constructing coverage where documented_class_count exceeds class_count should raise."""
    with pytest.raises(ValidationError):
        DocumentationCoverage(relative_path="a.py", class_count=1, documented_class_count=2)


def test_documentation_coverage_rejects_out_of_range_class_ratio() -> None:
    """Constructing coverage with a `class_documentation_ratio` outside [0.0, 1.0] should raise."""
    with pytest.raises(ValidationError):
        DocumentationCoverage(relative_path="a.py", class_documentation_ratio=1.5)


def test_documentation_coverage_rejects_out_of_range_function_ratio() -> None:
    """Constructing coverage with a `function_documentation_ratio` outside [0.0, 1.0] should
    raise."""
    with pytest.raises(ValidationError):
        DocumentationCoverage(relative_path="a.py", function_documentation_ratio=1.5)


def test_documentation_coverage_rejects_out_of_range_overall_ratio() -> None:
    """Constructing coverage with an `overall_documentation_ratio` outside [0.0, 1.0] should
    raise."""
    with pytest.raises(ValidationError):
        DocumentationCoverage(relative_path="a.py", overall_documentation_ratio=1.5)


def test_coverage_ratio_computes_a_normal_ratio() -> None:
    """`coverage_ratio` should divide normally when the total is positive."""
    assert coverage_ratio(1, 4) == 0.25


def test_coverage_ratio_returns_one_for_an_empty_population() -> None:
    """`coverage_ratio` should return `1.0` -- vacuously covered -- when total is zero."""
    assert coverage_ratio(0, 0) == 1.0


def test_coverage_ratio_rejects_a_negative_documented_count() -> None:
    """`coverage_ratio` should raise `ValidationError` for a negative documented count."""
    with pytest.raises(ValidationError):
        coverage_ratio(-1, 4)


def test_coverage_ratio_rejects_documented_exceeding_total() -> None:
    """`coverage_ratio` should raise `ValidationError` when documented exceeds total."""
    with pytest.raises(ValidationError):
        coverage_ratio(5, 4)
