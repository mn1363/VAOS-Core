"""Unit tests for `src.analyzers.metrics.base`."""

import pytest
from src.analyzers.metrics.base import (
    MetricsAnalysisResult,
    MetricsAnalyzer,
    NormalizedCodeMetrics,
    per_kloc,
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


def test_metrics_analyzer_cannot_be_instantiated_directly() -> None:
    """The abstract `MetricsAnalyzer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        MetricsAnalyzer()  # type: ignore[abstract]


def test_metrics_analysis_result_ok_builds_a_successful_result() -> None:
    """`MetricsAnalysisResult.ok` should set `succeeded=True` and carry the metrics."""
    metrics = NormalizedCodeMetrics(relative_path="a.py")

    result = MetricsAnalysisResult.ok(relative_path="a.py", metrics=metrics)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.metrics == metrics
    assert result.error_message is None


def test_metrics_analysis_result_failed_builds_a_failed_result() -> None:
    """`MetricsAnalysisResult.failed` should set `succeeded=False` and carry the error."""
    result = MetricsAnalysisResult.failed(relative_path="a.py", error_message="no data")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.metrics is None
    assert result.error_message == "no data"


def test_metrics_analysis_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    metrics = NormalizedCodeMetrics(relative_path="a.py")
    with pytest.raises(ValidationError):
        MetricsAnalysisResult(
            relative_path="a.py", succeeded=True, metrics=metrics, error_message="unexpected"
        )


def test_metrics_analysis_result_requires_metrics_on_success() -> None:
    """Constructing a successful result without metrics should raise."""
    with pytest.raises(ValidationError):
        MetricsAnalysisResult(relative_path="a.py", succeeded=True, metrics=None)


def test_metrics_analysis_result_rejects_metrics_on_failure() -> None:
    """Constructing a failed result with metrics attached should raise."""
    metrics = NormalizedCodeMetrics(relative_path="a.py")
    with pytest.raises(ValidationError):
        MetricsAnalysisResult(
            relative_path="a.py", succeeded=False, metrics=metrics, error_message="bad"
        )


def test_metrics_analysis_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        MetricsAnalysisResult(relative_path="a.py", succeeded=False)


def test_require_successful_extraction_returns_a_successful_result_unchanged() -> None:
    """`require_successful_extraction` should pass a successful result through unchanged."""
    extraction_result = _successful_extraction()
    assert require_successful_extraction(extraction_result) is extraction_result


def test_require_successful_extraction_rejects_a_failed_result() -> None:
    """`require_successful_extraction` should raise `ValidationError` for a failed result."""
    with pytest.raises(ValidationError):
        require_successful_extraction(_failed_extraction())


def test_normalized_code_metrics_is_frozen() -> None:
    """`NormalizedCodeMetrics` should be immutable once constructed."""
    metrics = NormalizedCodeMetrics(relative_path="a.py")
    with pytest.raises(AttributeError):
        metrics.relative_path = "b.py"  # type: ignore[misc]


def test_normalized_code_metrics_defaults() -> None:
    """`NormalizedCodeMetrics` should default every density field to zero."""
    metrics = NormalizedCodeMetrics(relative_path="a.py")
    assert metrics.line_count == 0
    assert metrics.classes_per_kloc == 0.0
    assert metrics.functions_per_kloc == 0.0
    assert metrics.methods_per_kloc == 0.0
    assert metrics.symbols_per_kloc == 0.0


def test_normalized_code_metrics_rejects_negative_line_count() -> None:
    """Constructing metrics with a negative line count should raise."""
    with pytest.raises(ValidationError):
        NormalizedCodeMetrics(relative_path="a.py", line_count=-1)


def test_normalized_code_metrics_rejects_negative_classes_per_kloc() -> None:
    """Constructing metrics with a negative `classes_per_kloc` should raise."""
    with pytest.raises(ValidationError):
        NormalizedCodeMetrics(relative_path="a.py", classes_per_kloc=-1.0)


def test_normalized_code_metrics_rejects_negative_functions_per_kloc() -> None:
    """Constructing metrics with a negative `functions_per_kloc` should raise."""
    with pytest.raises(ValidationError):
        NormalizedCodeMetrics(relative_path="a.py", functions_per_kloc=-1.0)


def test_normalized_code_metrics_rejects_negative_methods_per_kloc() -> None:
    """Constructing metrics with a negative `methods_per_kloc` should raise."""
    with pytest.raises(ValidationError):
        NormalizedCodeMetrics(relative_path="a.py", methods_per_kloc=-1.0)


def test_normalized_code_metrics_rejects_negative_symbols_per_kloc() -> None:
    """Constructing metrics with a negative `symbols_per_kloc` should raise."""
    with pytest.raises(ValidationError):
        NormalizedCodeMetrics(relative_path="a.py", symbols_per_kloc=-1.0)


def test_per_kloc_computes_a_normal_density() -> None:
    """`per_kloc` should normalize a count against a positive line count."""
    assert per_kloc(5, 500) == 10.0


def test_per_kloc_returns_zero_for_a_zero_line_count() -> None:
    """`per_kloc` should return `0.0` rather than raising when line_count is zero."""
    assert per_kloc(5, 0) == 0.0


def test_per_kloc_rejects_a_negative_count() -> None:
    """`per_kloc` should raise `ValidationError` for a negative count."""
    with pytest.raises(ValidationError):
        per_kloc(-1, 100)


def test_per_kloc_rejects_a_negative_line_count() -> None:
    """`per_kloc` should raise `ValidationError` for a negative line count."""
    with pytest.raises(ValidationError):
        per_kloc(1, -100)
