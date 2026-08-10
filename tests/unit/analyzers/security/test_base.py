"""Unit tests for `src.analyzers.security.base`."""

import pytest
from src.analyzers.security.base import (
    SecurityAnalysisResult,
    SecurityAnalyzer,
    SecurityAssessment,
    SecurityIndicator,
    require_successful_extraction,
)
from src.core.exceptions import ValidationError
from src.domain.entities import FindingSeverity
from src.extractors.imports.base import ImportExtractionResult


def _successful_extraction(relative_path: str = "a.py") -> ImportExtractionResult:
    """Build a minimal, successful `ImportExtractionResult` for use in analysis tests."""
    return ImportExtractionResult.ok(relative_path=relative_path, edges=())


def _failed_extraction(relative_path: str = "a.py") -> ImportExtractionResult:
    """Build a minimal, failed `ImportExtractionResult` for use in analysis tests."""
    return ImportExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_security_analyzer_cannot_be_instantiated_directly() -> None:
    """The abstract `SecurityAnalyzer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        SecurityAnalyzer()  # type: ignore[abstract]


def test_security_analysis_result_ok_builds_a_successful_result() -> None:
    """`SecurityAnalysisResult.ok` should set `succeeded=True` and carry the assessment."""
    assessment = SecurityAssessment(relative_path="a.py")

    result = SecurityAnalysisResult.ok(relative_path="a.py", assessment=assessment)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.assessment == assessment
    assert result.error_message is None


def test_security_analysis_result_failed_builds_a_failed_result() -> None:
    """`SecurityAnalysisResult.failed` should set `succeeded=False` and carry the error."""
    result = SecurityAnalysisResult.failed(relative_path="a.py", error_message="no data")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.assessment is None
    assert result.error_message == "no data"


def test_security_analysis_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    assessment = SecurityAssessment(relative_path="a.py")
    with pytest.raises(ValidationError):
        SecurityAnalysisResult(
            relative_path="a.py", succeeded=True, assessment=assessment, error_message="unexpected"
        )


def test_security_analysis_result_requires_assessment_on_success() -> None:
    """Constructing a successful result without an assessment should raise."""
    with pytest.raises(ValidationError):
        SecurityAnalysisResult(relative_path="a.py", succeeded=True, assessment=None)


def test_security_analysis_result_rejects_assessment_on_failure() -> None:
    """Constructing a failed result with an assessment attached should raise."""
    assessment = SecurityAssessment(relative_path="a.py")
    with pytest.raises(ValidationError):
        SecurityAnalysisResult(
            relative_path="a.py", succeeded=False, assessment=assessment, error_message="bad"
        )


def test_security_analysis_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        SecurityAnalysisResult(relative_path="a.py", succeeded=False)


def test_require_successful_extraction_returns_a_successful_result_unchanged() -> None:
    """`require_successful_extraction` should pass a successful result through unchanged."""
    extraction_result = _successful_extraction()
    assert require_successful_extraction(extraction_result) is extraction_result


def test_require_successful_extraction_rejects_a_failed_result() -> None:
    """`require_successful_extraction` should raise `ValidationError` for a failed result."""
    with pytest.raises(ValidationError):
        require_successful_extraction(_failed_extraction())


def test_security_indicator_is_frozen() -> None:
    """`SecurityIndicator` should be immutable once constructed."""
    indicator = SecurityIndicator(
        subject="requests",
        relative_path="a.py",
        severity=FindingSeverity.INFO,
        message="external dependency",
    )
    with pytest.raises(AttributeError):
        indicator.subject = "os"  # type: ignore[misc]


def test_security_indicator_rejects_blank_subject() -> None:
    """Constructing an indicator with a blank subject should raise."""
    with pytest.raises(ValidationError):
        SecurityIndicator(
            subject=" ", relative_path="a.py", severity=FindingSeverity.INFO, message="x"
        )


def test_security_indicator_rejects_blank_message() -> None:
    """Constructing an indicator with a blank message should raise."""
    with pytest.raises(ValidationError):
        SecurityIndicator(
            subject="requests", relative_path="a.py", severity=FindingSeverity.INFO, message=" "
        )


def test_security_assessment_is_frozen() -> None:
    """`SecurityAssessment` should be immutable once constructed."""
    assessment = SecurityAssessment(relative_path="a.py")
    with pytest.raises(AttributeError):
        assessment.relative_path = "b.py"  # type: ignore[misc]


def test_security_assessment_defaults() -> None:
    """`SecurityAssessment` should default every field to empty/zero."""
    assessment = SecurityAssessment(relative_path="a.py")
    assert assessment.external_dependency_count == 0
    assert assessment.external_targets == ()
    assert assessment.indicators == ()


def test_security_assessment_rejects_negative_count() -> None:
    """Constructing an assessment with a negative count should raise."""
    with pytest.raises(ValidationError):
        SecurityAssessment(relative_path="a.py", external_dependency_count=-1)


def test_security_assessment_rejects_unsorted_external_targets() -> None:
    """Constructing an assessment with unsorted external targets should raise."""
    with pytest.raises(ValidationError):
        SecurityAssessment(relative_path="a.py", external_targets=("sys", "os"))


def test_security_assessment_rejects_duplicate_external_targets() -> None:
    """Constructing an assessment with duplicate external targets should raise."""
    with pytest.raises(ValidationError):
        SecurityAssessment(relative_path="a.py", external_targets=("os", "os"))


def test_security_assessment_carries_indicators() -> None:
    """`SecurityAssessment` should carry through its indicators unchanged."""
    indicator = SecurityIndicator(
        subject="requests",
        relative_path="a.py",
        severity=FindingSeverity.INFO,
        message="external dependency surface",
    )
    assessment = SecurityAssessment(
        relative_path="a.py",
        external_dependency_count=1,
        external_targets=("requests",),
        indicators=(indicator,),
    )
    assert assessment.indicators == (indicator,)
