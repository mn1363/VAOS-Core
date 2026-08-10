"""Unit tests for `src.analyzers.quality.base`."""

import pytest
from src.analyzers.quality.base import (
    QualityAnalysisResult,
    QualityAnalyzer,
    QualityAssessment,
    QualityIndicator,
    require_successful_extraction,
)
from src.core.exceptions import ValidationError
from src.domain.entities import FindingSeverity
from src.extractors.foundation.base import FoundationExtractionResult


def _successful_extraction(relative_path: str = "a.py") -> FoundationExtractionResult:
    """Build a minimal, successful `FoundationExtractionResult` for use in analysis tests."""
    return FoundationExtractionResult.ok(relative_path=relative_path, candidates=())


def _failed_extraction(relative_path: str = "a.py") -> FoundationExtractionResult:
    """Build a minimal, failed `FoundationExtractionResult` for use in analysis tests."""
    return FoundationExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_quality_analyzer_cannot_be_instantiated_directly() -> None:
    """The abstract `QualityAnalyzer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        QualityAnalyzer()  # type: ignore[abstract]


def test_quality_analysis_result_ok_builds_a_successful_result() -> None:
    """`QualityAnalysisResult.ok` should set `succeeded=True` and carry the assessment."""
    assessment = QualityAssessment(relative_path="a.py")

    result = QualityAnalysisResult.ok(relative_path="a.py", assessment=assessment)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.assessment == assessment
    assert result.error_message is None


def test_quality_analysis_result_failed_builds_a_failed_result() -> None:
    """`QualityAnalysisResult.failed` should set `succeeded=False` and carry the error."""
    result = QualityAnalysisResult.failed(relative_path="a.py", error_message="no data")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.assessment is None
    assert result.error_message == "no data"


def test_quality_analysis_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    assessment = QualityAssessment(relative_path="a.py")
    with pytest.raises(ValidationError):
        QualityAnalysisResult(
            relative_path="a.py", succeeded=True, assessment=assessment, error_message="unexpected"
        )


def test_quality_analysis_result_requires_assessment_on_success() -> None:
    """Constructing a successful result without an assessment should raise."""
    with pytest.raises(ValidationError):
        QualityAnalysisResult(relative_path="a.py", succeeded=True, assessment=None)


def test_quality_analysis_result_rejects_assessment_on_failure() -> None:
    """Constructing a failed result with an assessment attached should raise."""
    assessment = QualityAssessment(relative_path="a.py")
    with pytest.raises(ValidationError):
        QualityAnalysisResult(
            relative_path="a.py", succeeded=False, assessment=assessment, error_message="bad"
        )


def test_quality_analysis_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        QualityAnalysisResult(relative_path="a.py", succeeded=False)


def test_require_successful_extraction_returns_a_successful_result_unchanged() -> None:
    """`require_successful_extraction` should pass a successful result through unchanged."""
    extraction_result = _successful_extraction()
    assert require_successful_extraction(extraction_result) is extraction_result


def test_require_successful_extraction_rejects_a_failed_result() -> None:
    """`require_successful_extraction` should raise `ValidationError` for a failed result."""
    with pytest.raises(ValidationError):
        require_successful_extraction(_failed_extraction())


def test_quality_indicator_is_frozen() -> None:
    """`QualityIndicator` should be immutable once constructed."""
    indicator = QualityIndicator(
        subject_name="Foo",
        relative_path="a.py",
        severity=FindingSeverity.LOW,
        message="missing docstring",
    )
    with pytest.raises(AttributeError):
        indicator.subject_name = "Bar"  # type: ignore[misc]


def test_quality_indicator_rejects_blank_subject_name() -> None:
    """Constructing an indicator with a blank subject_name should raise."""
    with pytest.raises(ValidationError):
        QualityIndicator(
            subject_name="  ", relative_path="a.py", severity=FindingSeverity.LOW, message="x"
        )


def test_quality_indicator_rejects_blank_message() -> None:
    """Constructing an indicator with a blank message should raise."""
    with pytest.raises(ValidationError):
        QualityIndicator(
            subject_name="Foo", relative_path="a.py", severity=FindingSeverity.LOW, message=" "
        )


def test_quality_assessment_is_frozen() -> None:
    """`QualityAssessment` should be immutable once constructed."""
    assessment = QualityAssessment(relative_path="a.py")
    with pytest.raises(AttributeError):
        assessment.relative_path = "b.py"  # type: ignore[misc]


def test_quality_assessment_defaults_to_vacuously_documented() -> None:
    """`QualityAssessment` should default `documented_public_ratio` to `1.0`."""
    assessment = QualityAssessment(relative_path="a.py")
    assert assessment.candidate_count == 0
    assert assessment.public_candidate_count == 0
    assert assessment.documented_public_ratio == 1.0
    assert assessment.indicators == ()


def test_quality_assessment_rejects_negative_counts() -> None:
    """Constructing an assessment with a negative count should raise."""
    with pytest.raises(ValidationError):
        QualityAssessment(relative_path="a.py", candidate_count=-1)


def test_quality_assessment_rejects_public_exceeding_total() -> None:
    """Constructing an assessment where public exceeds total candidates should raise."""
    with pytest.raises(ValidationError):
        QualityAssessment(relative_path="a.py", candidate_count=1, public_candidate_count=2)


def test_quality_assessment_rejects_out_of_range_ratio() -> None:
    """Constructing an assessment with a ratio outside [0.0, 1.0] should raise."""
    with pytest.raises(ValidationError):
        QualityAssessment(relative_path="a.py", documented_public_ratio=1.5)


def test_quality_assessment_carries_indicators() -> None:
    """`QualityAssessment` should carry through its indicators unchanged."""
    indicator = QualityIndicator(
        subject_name="Foo",
        relative_path="a.py",
        severity=FindingSeverity.MEDIUM,
        message="public class has no docstring",
    )
    assessment = QualityAssessment(
        relative_path="a.py",
        candidate_count=1,
        public_candidate_count=1,
        documented_public_ratio=0.0,
        indicators=(indicator,),
    )
    assert assessment.indicators == (indicator,)
