"""Unit tests for `src.analyzers.architecture.base`."""

import pytest
from src.analyzers.architecture.base import (
    ArchitectureAnalysisResult,
    ArchitectureAnalyzer,
    ArchitectureAssessment,
    require_successful_extraction,
)
from src.core.exceptions import ValidationError
from src.extractors.architecture.base import ArchitectureExtractionResult, PackageUnit


def _successful_extraction(relative_path: str = "a.py") -> ArchitectureExtractionResult:
    """Build a minimal, successful `ArchitectureExtractionResult` for use in analysis tests."""
    unit = PackageUnit(relative_path=relative_path, package_path=("src", "a"))
    return ArchitectureExtractionResult.ok(relative_path=relative_path, unit=unit)


def _failed_extraction(relative_path: str = "a.py") -> ArchitectureExtractionResult:
    """Build a minimal, failed `ArchitectureExtractionResult` for use in analysis tests."""
    return ArchitectureExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_architecture_analyzer_cannot_be_instantiated_directly() -> None:
    """The abstract `ArchitectureAnalyzer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        ArchitectureAnalyzer()  # type: ignore[abstract]


def test_architecture_analysis_result_ok_builds_a_successful_result() -> None:
    """`ArchitectureAnalysisResult.ok` should set `succeeded=True` and carry the assessment."""
    assessment = ArchitectureAssessment(relative_path="a.py", package_path=("src", "a"))

    result = ArchitectureAnalysisResult.ok(relative_path="a.py", assessment=assessment)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.assessment == assessment
    assert result.error_message is None


def test_architecture_analysis_result_failed_builds_a_failed_result() -> None:
    """`ArchitectureAnalysisResult.failed` should set `succeeded=False` and carry the error."""
    result = ArchitectureAnalysisResult.failed(relative_path="a.py", error_message="no data")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.assessment is None
    assert result.error_message == "no data"


def test_architecture_analysis_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    assessment = ArchitectureAssessment(relative_path="a.py", package_path=("src",))
    with pytest.raises(ValidationError):
        ArchitectureAnalysisResult(
            relative_path="a.py", succeeded=True, assessment=assessment, error_message="unexpected"
        )


def test_architecture_analysis_result_requires_assessment_on_success() -> None:
    """Constructing a successful result without an assessment should raise."""
    with pytest.raises(ValidationError):
        ArchitectureAnalysisResult(relative_path="a.py", succeeded=True, assessment=None)


def test_architecture_analysis_result_rejects_assessment_on_failure() -> None:
    """Constructing a failed result with an assessment attached should raise."""
    assessment = ArchitectureAssessment(relative_path="a.py", package_path=("src",))
    with pytest.raises(ValidationError):
        ArchitectureAnalysisResult(
            relative_path="a.py", succeeded=False, assessment=assessment, error_message="bad"
        )


def test_architecture_analysis_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        ArchitectureAnalysisResult(relative_path="a.py", succeeded=False)


def test_require_successful_extraction_returns_a_successful_result_unchanged() -> None:
    """`require_successful_extraction` should pass a successful result through unchanged."""
    extraction_result = _successful_extraction()
    assert require_successful_extraction(extraction_result) is extraction_result


def test_require_successful_extraction_rejects_a_failed_result() -> None:
    """`require_successful_extraction` should raise `ValidationError` for a failed result."""
    with pytest.raises(ValidationError):
        require_successful_extraction(_failed_extraction())


def test_architecture_assessment_is_frozen() -> None:
    """`ArchitectureAssessment` should be immutable once constructed."""
    assessment = ArchitectureAssessment(relative_path="a.py", package_path=("src",))
    with pytest.raises(AttributeError):
        assessment.relative_path = "b.py"  # type: ignore[misc]


def test_architecture_assessment_defaults() -> None:
    """`ArchitectureAssessment` should default its optional fields sensibly."""
    assessment = ArchitectureAssessment(relative_path="a.py", package_path=())
    assert assessment.package_depth == 0
    assert assessment.is_package_root is False
    assert assessment.declared_module_count == 0


def test_architecture_assessment_rejects_negative_declared_module_count() -> None:
    """Constructing an assessment with a negative declared-module count should raise."""
    with pytest.raises(ValidationError):
        ArchitectureAssessment(
            relative_path="a.py",
            package_path=("src",),
            declared_module_count=-1,
        )


def test_architecture_assessment_computes_depth_from_path() -> None:
    """`package_depth` should always equal `len(package_path)`, computed rather than stored."""
    assessment = ArchitectureAssessment(
        relative_path="src/a/b.py",
        package_path=("src", "a"),
        is_package_root=True,
        declared_module_count=3,
    )
    assert assessment.package_depth == 2
    assert assessment.is_package_root is True
    assert assessment.declared_module_count == 3


def test_architecture_assessment_package_depth_tracks_empty_path() -> None:
    """`package_depth` should be `0` when `package_path` is empty."""
    assessment = ArchitectureAssessment(relative_path="a.py", package_path=())
    assert assessment.package_depth == 0
