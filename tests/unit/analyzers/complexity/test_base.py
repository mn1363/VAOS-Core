"""Unit tests for `src.analyzers.complexity.base`."""

import pytest
from src.analyzers.complexity.base import (
    ComplexityAnalysisResult,
    ComplexityAnalyzer,
    ComplexityMetrics,
    require_successful_extraction,
    safe_ratio,
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


def test_complexity_analyzer_cannot_be_instantiated_directly() -> None:
    """The abstract `ComplexityAnalyzer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        ComplexityAnalyzer()  # type: ignore[abstract]


def test_complexity_analysis_result_ok_builds_a_successful_result() -> None:
    """`ComplexityAnalysisResult.ok` should set `succeeded=True` and carry the metrics."""
    metrics = ComplexityMetrics(relative_path="a.py")

    result = ComplexityAnalysisResult.ok(relative_path="a.py", metrics=metrics)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.metrics == metrics
    assert result.error_message is None


def test_complexity_analysis_result_failed_builds_a_failed_result() -> None:
    """`ComplexityAnalysisResult.failed` should set `succeeded=False` and carry the error."""
    result = ComplexityAnalysisResult.failed(relative_path="a.py", error_message="no data")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.metrics is None
    assert result.error_message == "no data"


def test_complexity_analysis_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    metrics = ComplexityMetrics(relative_path="a.py")
    with pytest.raises(ValidationError):
        ComplexityAnalysisResult(
            relative_path="a.py", succeeded=True, metrics=metrics, error_message="unexpected"
        )


def test_complexity_analysis_result_requires_metrics_on_success() -> None:
    """Constructing a successful result without metrics should raise."""
    with pytest.raises(ValidationError):
        ComplexityAnalysisResult(relative_path="a.py", succeeded=True, metrics=None)


def test_complexity_analysis_result_rejects_metrics_on_failure() -> None:
    """Constructing a failed result with metrics attached should raise."""
    metrics = ComplexityMetrics(relative_path="a.py")
    with pytest.raises(ValidationError):
        ComplexityAnalysisResult(
            relative_path="a.py", succeeded=False, metrics=metrics, error_message="bad"
        )


def test_complexity_analysis_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        ComplexityAnalysisResult(relative_path="a.py", succeeded=False)


def test_require_successful_extraction_returns_a_successful_result_unchanged() -> None:
    """`require_successful_extraction` should pass a successful result through unchanged."""
    extraction_result = _successful_extraction()
    assert require_successful_extraction(extraction_result) is extraction_result


def test_require_successful_extraction_rejects_a_failed_result() -> None:
    """`require_successful_extraction` should raise `ValidationError` for a failed result."""
    with pytest.raises(ValidationError):
        require_successful_extraction(_failed_extraction())


def test_complexity_metrics_is_frozen() -> None:
    """`ComplexityMetrics` should be immutable once constructed."""
    metrics = ComplexityMetrics(relative_path="a.py")
    with pytest.raises(AttributeError):
        metrics.relative_path = "b.py"  # type: ignore[misc]


def test_complexity_metrics_defaults() -> None:
    """`ComplexityMetrics` should default every ratio and count field to zero."""
    metrics = ComplexityMetrics(relative_path="a.py")
    assert metrics.methods_per_class == 0.0
    assert metrics.lines_per_function == 0.0
    assert metrics.async_function_ratio == 0.0
    assert metrics.class_count == 0
    assert metrics.function_count == 0
    assert metrics.method_count == 0


def test_complexity_metrics_rejects_negative_methods_per_class() -> None:
    """Constructing metrics with a negative `methods_per_class` should raise."""
    with pytest.raises(ValidationError):
        ComplexityMetrics(relative_path="a.py", methods_per_class=-1.0)


def test_complexity_metrics_rejects_negative_lines_per_function() -> None:
    """Constructing metrics with a negative `lines_per_function` should raise."""
    with pytest.raises(ValidationError):
        ComplexityMetrics(relative_path="a.py", lines_per_function=-1.0)


def test_complexity_metrics_rejects_negative_class_count() -> None:
    """Constructing metrics with a negative `class_count` should raise."""
    with pytest.raises(ValidationError):
        ComplexityMetrics(relative_path="a.py", class_count=-1)


def test_complexity_metrics_rejects_negative_function_count() -> None:
    """Constructing metrics with a negative `function_count` should raise."""
    with pytest.raises(ValidationError):
        ComplexityMetrics(relative_path="a.py", function_count=-1)


def test_complexity_metrics_rejects_negative_method_count() -> None:
    """Constructing metrics with a negative `method_count` should raise."""
    with pytest.raises(ValidationError):
        ComplexityMetrics(relative_path="a.py", method_count=-1)


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_complexity_metrics_rejects_out_of_range_async_ratio(value: float) -> None:
    """Constructing metrics with an `async_function_ratio` outside [0.0, 1.0] should raise."""
    with pytest.raises(ValidationError):
        ComplexityMetrics(relative_path="a.py", async_function_ratio=value)


def test_safe_ratio_computes_a_normal_ratio() -> None:
    """`safe_ratio` should divide normally when the denominator is positive."""
    assert safe_ratio(6, 3) == 2.0


def test_safe_ratio_returns_zero_for_a_zero_denominator() -> None:
    """`safe_ratio` should return `0.0` rather than raising when the denominator is zero."""
    assert safe_ratio(5, 0) == 0.0


def test_safe_ratio_rejects_a_negative_numerator() -> None:
    """`safe_ratio` should raise `ValidationError` for a negative numerator."""
    with pytest.raises(ValidationError):
        safe_ratio(-1, 3)
