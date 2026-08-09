"""Unit tests for `src.extractors.foundation.base`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.foundation.base import (
    FoundationCandidate,
    FoundationCandidateKind,
    FoundationExtractionResult,
    FoundationExtractor,
    require_successful_parse,
)
from src.parsers.base import FileMetadata, ParseResult


def _metadata() -> FileMetadata:
    """Build a minimal, valid `FileMetadata` for use in `ParseResult` construction."""
    return FileMetadata(
        relative_path="a.py",
        language=SourceLanguage.PYTHON,
        size_bytes=1,
        line_count=1,
        content_hash="deadbeef",
    )


def _successful_parse_result(relative_path: str = "a.py") -> ParseResult:
    """Build a minimal, successful `ParseResult` for use in extraction tests."""
    return ParseResult.ok(
        relative_path=relative_path, language=SourceLanguage.PYTHON, metadata=_metadata()
    )


def _failed_parse_result(relative_path: str = "a.py") -> ParseResult:
    """Build a minimal, failed `ParseResult` for use in extraction tests."""
    return ParseResult.failed(
        relative_path=relative_path, language=SourceLanguage.PYTHON, error_message="bad syntax"
    )


def test_foundation_extractor_cannot_be_instantiated_directly() -> None:
    """The abstract `FoundationExtractor` Port must not be instantiable."""
    with pytest.raises(TypeError):
        FoundationExtractor()  # type: ignore[abstract]


def test_foundation_extraction_result_ok_builds_a_successful_result() -> None:
    """`FoundationExtractionResult.ok` should set `succeeded=True` and carry the candidates."""
    candidate = FoundationCandidate(
        name="retry", kind=FoundationCandidateKind.FUNCTION, relative_path="a.py"
    )

    result = FoundationExtractionResult.ok(relative_path="a.py", candidates=[candidate])

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.candidates == (candidate,)
    assert result.error_message is None


def test_foundation_extraction_result_ok_defaults_to_no_candidates() -> None:
    """`FoundationExtractionResult.ok` should accept an omitted `candidates` sequence as empty."""
    result = FoundationExtractionResult.ok(relative_path="a.py")
    assert result.candidates == ()


def test_foundation_extraction_result_failed_builds_a_failed_result() -> None:
    """`FoundationExtractionResult.failed` should set `succeeded=False` and carry the error."""
    result = FoundationExtractionResult.failed(relative_path="a.py", error_message="went wrong")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.candidates == ()
    assert result.error_message == "went wrong"


def test_foundation_extraction_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    with pytest.raises(ValidationError):
        FoundationExtractionResult(
            relative_path="a.py", succeeded=True, error_message="unexpected"
        )


def test_foundation_extraction_result_rejects_candidates_on_failure() -> None:
    """Constructing a failed result with candidates attached should raise."""
    candidate = FoundationCandidate(
        name="retry", kind=FoundationCandidateKind.FUNCTION, relative_path="a.py"
    )
    with pytest.raises(ValidationError):
        FoundationExtractionResult(
            relative_path="a.py",
            succeeded=False,
            candidates=(candidate,),
            error_message="went wrong",
        )


def test_foundation_extraction_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        FoundationExtractionResult(relative_path="a.py", succeeded=False)


def test_require_successful_parse_returns_a_successful_result_unchanged() -> None:
    """`require_successful_parse` should pass a successful `ParseResult` through unchanged."""
    parse_result = _successful_parse_result()
    assert require_successful_parse(parse_result) is parse_result


def test_require_successful_parse_rejects_a_failed_result() -> None:
    """`require_successful_parse` should raise `ValidationError` for a failed `ParseResult`."""
    with pytest.raises(ValidationError):
        require_successful_parse(_failed_parse_result())


def test_foundation_candidate_is_frozen() -> None:
    """`FoundationCandidate` should be immutable once constructed."""
    candidate = FoundationCandidate(
        name="retry", kind=FoundationCandidateKind.FUNCTION, relative_path="a.py"
    )
    with pytest.raises(AttributeError):
        candidate.name = "other"  # type: ignore[misc]


def test_foundation_candidate_defaults() -> None:
    """`FoundationCandidate` should default its optional fields sensibly."""
    candidate = FoundationCandidate(
        name="retry", kind=FoundationCandidateKind.FUNCTION, relative_path="a.py"
    )

    assert candidate.is_public is False
    assert candidate.has_docstring is False
    assert candidate.signals == ()
    assert candidate.line_number == 0


def test_foundation_candidate_carries_signals() -> None:
    """`FoundationCandidate` should carry through freeform signal entries."""
    candidate = FoundationCandidate(
        name="retry",
        kind=FoundationCandidateKind.FUNCTION,
        relative_path="a.py",
        is_public=True,
        has_docstring=True,
        signals=("no base classes", "decorated with @dataclass"),
    )

    assert candidate.is_public is True
    assert candidate.has_docstring is True
    assert candidate.signals == ("no base classes", "decorated with @dataclass")
