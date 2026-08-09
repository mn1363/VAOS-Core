"""Unit tests for `src.extractors.patterns.base`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.patterns.base import (
    ExtractedPattern,
    PatternExtractionResult,
    PatternExtractor,
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


def test_pattern_extractor_cannot_be_instantiated_directly() -> None:
    """The abstract `PatternExtractor` Port must not be instantiable."""
    with pytest.raises(TypeError):
        PatternExtractor()  # type: ignore[abstract]


def test_pattern_extraction_result_ok_builds_a_successful_result() -> None:
    """`PatternExtractionResult.ok` should set `succeeded=True` and carry the patterns."""
    pattern = ExtractedPattern(
        name="factory_method",
        relative_path="a.py",
        subject_name="build",
        description="Returns a new instance of its enclosing class.",
    )

    result = PatternExtractionResult.ok(relative_path="a.py", patterns=[pattern])

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.patterns == (pattern,)
    assert result.error_message is None


def test_pattern_extraction_result_ok_defaults_to_no_patterns() -> None:
    """`PatternExtractionResult.ok` should accept an omitted `patterns` sequence as empty."""
    result = PatternExtractionResult.ok(relative_path="a.py")
    assert result.patterns == ()


def test_pattern_extraction_result_failed_builds_a_failed_result() -> None:
    """`PatternExtractionResult.failed` should set `succeeded=False` and carry the error."""
    result = PatternExtractionResult.failed(relative_path="a.py", error_message="went wrong")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.patterns == ()
    assert result.error_message == "went wrong"


def test_pattern_extraction_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    with pytest.raises(ValidationError):
        PatternExtractionResult(relative_path="a.py", succeeded=True, error_message="unexpected")


def test_pattern_extraction_result_rejects_patterns_on_failure() -> None:
    """Constructing a failed result with patterns attached should raise."""
    pattern = ExtractedPattern(
        name="factory_method", relative_path="a.py", subject_name="build", description="d"
    )
    with pytest.raises(ValidationError):
        PatternExtractionResult(
            relative_path="a.py",
            succeeded=False,
            patterns=(pattern,),
            error_message="went wrong",
        )


def test_pattern_extraction_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        PatternExtractionResult(relative_path="a.py", succeeded=False)


def test_require_successful_parse_returns_a_successful_result_unchanged() -> None:
    """`require_successful_parse` should pass a successful `ParseResult` through unchanged."""
    parse_result = _successful_parse_result()
    assert require_successful_parse(parse_result) is parse_result


def test_require_successful_parse_rejects_a_failed_result() -> None:
    """`require_successful_parse` should raise `ValidationError` for a failed `ParseResult`."""
    with pytest.raises(ValidationError):
        require_successful_parse(_failed_parse_result())


def test_extracted_pattern_is_frozen() -> None:
    """`ExtractedPattern` should be immutable once constructed."""
    pattern = ExtractedPattern(
        name="factory_method", relative_path="a.py", subject_name="build", description="d"
    )
    with pytest.raises(AttributeError):
        pattern.name = "other"  # type: ignore[misc]


def test_extracted_pattern_defaults() -> None:
    """`ExtractedPattern` should default its optional fields sensibly."""
    pattern = ExtractedPattern(
        name="factory_method", relative_path="a.py", subject_name="build", description="d"
    )

    assert pattern.line_number == 0
    assert pattern.evidence == ()


def test_extracted_pattern_carries_evidence() -> None:
    """`ExtractedPattern` should carry through freeform evidence entries."""
    pattern = ExtractedPattern(
        name="factory_method",
        relative_path="a.py",
        subject_name="build",
        description="d",
        evidence=("returns cls(...)", "classmethod"),
    )
    assert pattern.evidence == ("returns cls(...)", "classmethod")
