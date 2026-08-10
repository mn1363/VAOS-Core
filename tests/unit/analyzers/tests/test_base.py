"""Unit tests for `src.analyzers.tests.base`."""

import pytest
from src.analyzers.tests.base import (
    TestEvidence,
    TestIndicator,
    TestsAnalysisResult,
    TestsAnalyzer,
    is_test_file,
    is_test_symbol_name,
    require_successful_extraction,
)
from src.core.exceptions import ValidationError
from src.domain.entities import FindingSeverity
from src.extractors.symbols.base import ExtractedSymbolKind, SymbolExtractionResult


def _successful_extraction(relative_path: str = "a.py") -> SymbolExtractionResult:
    """Build a minimal, successful `SymbolExtractionResult` for use in analysis tests."""
    return SymbolExtractionResult.ok(relative_path=relative_path, symbols=())


def _failed_extraction(relative_path: str = "a.py") -> SymbolExtractionResult:
    """Build a minimal, failed `SymbolExtractionResult` for use in analysis tests."""
    return SymbolExtractionResult.failed(relative_path=relative_path, error_message="bad")


def test_tests_analyzer_cannot_be_instantiated_directly() -> None:
    """The abstract `TestsAnalyzer` Port must not be instantiable."""
    with pytest.raises(TypeError):
        TestsAnalyzer()  # type: ignore[abstract]


def test_tests_analysis_result_ok_builds_a_successful_result() -> None:
    """`TestsAnalysisResult.ok` should set `succeeded=True` and carry the evidence."""
    evidence = TestEvidence(relative_path="test_a.py")

    result = TestsAnalysisResult.ok(relative_path="test_a.py", evidence=evidence)

    assert result.succeeded is True
    assert result.relative_path == "test_a.py"
    assert result.evidence == evidence
    assert result.error_message is None


def test_tests_analysis_result_failed_builds_a_failed_result() -> None:
    """`TestsAnalysisResult.failed` should set `succeeded=False` and carry the error."""
    result = TestsAnalysisResult.failed(relative_path="a.py", error_message="no data")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.evidence is None
    assert result.error_message == "no data"


def test_tests_analysis_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    evidence = TestEvidence(relative_path="a.py")
    with pytest.raises(ValidationError):
        TestsAnalysisResult(
            relative_path="a.py", succeeded=True, evidence=evidence, error_message="unexpected"
        )


def test_tests_analysis_result_requires_evidence_on_success() -> None:
    """Constructing a successful result without evidence should raise."""
    with pytest.raises(ValidationError):
        TestsAnalysisResult(relative_path="a.py", succeeded=True, evidence=None)


def test_tests_analysis_result_rejects_evidence_on_failure() -> None:
    """Constructing a failed result with evidence attached should raise."""
    evidence = TestEvidence(relative_path="a.py")
    with pytest.raises(ValidationError):
        TestsAnalysisResult(
            relative_path="a.py", succeeded=False, evidence=evidence, error_message="bad"
        )


def test_tests_analysis_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        TestsAnalysisResult(relative_path="a.py", succeeded=False)


def test_require_successful_extraction_returns_a_successful_result_unchanged() -> None:
    """`require_successful_extraction` should pass a successful result through unchanged."""
    extraction_result = _successful_extraction()
    assert require_successful_extraction(extraction_result) is extraction_result


def test_require_successful_extraction_rejects_a_failed_result() -> None:
    """`require_successful_extraction` should raise `ValidationError` for a failed result."""
    with pytest.raises(ValidationError):
        require_successful_extraction(_failed_extraction())


def test_test_indicator_is_frozen() -> None:
    """`TestIndicator` should be immutable once constructed."""
    indicator = TestIndicator(
        subject_name="test_a.py",
        relative_path="test_a.py",
        severity=FindingSeverity.LOW,
        message="no test-shaped symbols found",
    )
    with pytest.raises(AttributeError):
        indicator.subject_name = "b.py"  # type: ignore[misc]


def test_test_indicator_rejects_blank_subject_name() -> None:
    """Constructing an indicator with a blank subject_name should raise."""
    with pytest.raises(ValidationError):
        TestIndicator(
            subject_name=" ", relative_path="a.py", severity=FindingSeverity.LOW, message="x"
        )


def test_test_indicator_rejects_blank_message() -> None:
    """Constructing an indicator with a blank message should raise."""
    with pytest.raises(ValidationError):
        TestIndicator(
            subject_name="a", relative_path="a.py", severity=FindingSeverity.LOW, message=" "
        )


def test_test_evidence_is_frozen() -> None:
    """`TestEvidence` should be immutable once constructed."""
    evidence = TestEvidence(relative_path="a.py")
    with pytest.raises(AttributeError):
        evidence.relative_path = "b.py"  # type: ignore[misc]


def test_test_evidence_defaults() -> None:
    """`TestEvidence` should default to no test signal found."""
    evidence = TestEvidence(relative_path="a.py")
    assert evidence.is_test_file is False
    assert evidence.test_function_count == 0
    assert evidence.test_class_count == 0
    assert evidence.indicators == ()


def test_test_evidence_rejects_negative_counts() -> None:
    """Constructing evidence with a negative test count should raise."""
    with pytest.raises(ValidationError):
        TestEvidence(relative_path="a.py", test_function_count=-1)


@pytest.mark.parametrize(
    "relative_path,expected",
    [
        ("tests/unit/test_base.py", True),
        ("test/test_base.py", True),
        ("test_base.py", True),
        ("base_test.py", True),
        ("src/analyzers/architecture/base.py", False),
        ("src/testing_utils.py", False),
    ],
)
def test_is_test_file_recognizes_conventions(relative_path: str, expected: bool) -> None:
    """`is_test_file` should recognize test-directory and test-filename conventions."""
    assert is_test_file(relative_path) is expected


@pytest.mark.parametrize(
    "name,kind,expected",
    [
        ("test_something", ExtractedSymbolKind.FUNCTION, True),
        ("test_something", ExtractedSymbolKind.METHOD, True),
        ("something", ExtractedSymbolKind.FUNCTION, False),
        ("TestSomething", ExtractedSymbolKind.CLASS, True),
        ("Something", ExtractedSymbolKind.CLASS, False),
        ("TEST_VALUE", ExtractedSymbolKind.CONSTANT, False),
    ],
)
def test_is_test_symbol_name_recognizes_conventions(
    name: str, kind: ExtractedSymbolKind, expected: bool
) -> None:
    """`is_test_symbol_name` should recognize per-kind test-naming conventions."""
    assert is_test_symbol_name(name, kind) is expected
