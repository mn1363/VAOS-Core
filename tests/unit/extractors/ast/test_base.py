"""Unit tests for `src.extractors.ast.base`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.ast.base import (
    AstExtractionResult,
    AstExtractor,
    AstMetadata,
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


def test_ast_extractor_cannot_be_instantiated_directly() -> None:
    """The abstract `AstExtractor` Port must not be instantiable."""
    with pytest.raises(TypeError):
        AstExtractor()  # type: ignore[abstract]


def test_ast_metadata_defaults_every_count_to_zero() -> None:
    """`AstMetadata` should default every count field to zero."""
    metadata = AstMetadata(relative_path="a.py")

    assert metadata.class_count == 0
    assert metadata.function_count == 0
    assert metadata.method_count == 0
    assert metadata.import_count == 0
    assert metadata.export_count == 0
    assert metadata.symbol_count == 0
    assert metadata.module_count == 0
    assert metadata.async_function_count == 0
    assert metadata.documented_class_count == 0
    assert metadata.documented_function_count == 0
    assert metadata.line_count == 0


def test_ast_metadata_accepts_positive_counts() -> None:
    """`AstMetadata` should accept explicit positive counts."""
    metadata = AstMetadata(relative_path="a.py", class_count=3, function_count=5, line_count=120)

    assert metadata.class_count == 3
    assert metadata.function_count == 5
    assert metadata.line_count == 120


@pytest.mark.parametrize(
    "field_name",
    [
        "class_count",
        "function_count",
        "method_count",
        "import_count",
        "export_count",
        "symbol_count",
        "module_count",
        "async_function_count",
        "documented_class_count",
        "documented_function_count",
        "line_count",
    ],
)
def test_ast_metadata_rejects_a_negative_count(field_name: str) -> None:
    """`AstMetadata` should reject a negative value for any count field."""
    with pytest.raises(ValidationError):
        AstMetadata(relative_path="a.py", **{field_name: -1})


def test_ast_extraction_result_ok_builds_a_successful_result() -> None:
    """`AstExtractionResult.ok` should set `succeeded=True` and carry the metadata."""
    metadata = AstMetadata(relative_path="a.py", class_count=1)

    result = AstExtractionResult.ok(relative_path="a.py", metadata=metadata)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.metadata == metadata
    assert result.error_message is None


def test_ast_extraction_result_failed_builds_a_failed_result() -> None:
    """`AstExtractionResult.failed` should set `succeeded=False` and carry the error message."""
    result = AstExtractionResult.failed(relative_path="a.py", error_message="no metadata")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.metadata is None
    assert result.error_message == "no metadata"


def test_ast_extraction_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    metadata = AstMetadata(relative_path="a.py")
    with pytest.raises(ValidationError):
        AstExtractionResult(
            relative_path="a.py", succeeded=True, metadata=metadata, error_message="unexpected"
        )


def test_ast_extraction_result_requires_metadata_on_success() -> None:
    """Constructing a successful result without metadata should raise."""
    with pytest.raises(ValidationError):
        AstExtractionResult(relative_path="a.py", succeeded=True, metadata=None)


def test_ast_extraction_result_rejects_metadata_on_failure() -> None:
    """Constructing a failed result with metadata attached should raise."""
    metadata = AstMetadata(relative_path="a.py")
    with pytest.raises(ValidationError):
        AstExtractionResult(
            relative_path="a.py", succeeded=False, metadata=metadata, error_message="went wrong"
        )


def test_ast_extraction_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        AstExtractionResult(relative_path="a.py", succeeded=False)


def test_require_successful_parse_returns_a_successful_result_unchanged() -> None:
    """`require_successful_parse` should pass a successful `ParseResult` through unchanged."""
    parse_result = _successful_parse_result()
    assert require_successful_parse(parse_result) is parse_result


def test_require_successful_parse_rejects_a_failed_result() -> None:
    """`require_successful_parse` should raise `ValidationError` for a failed `ParseResult`."""
    with pytest.raises(ValidationError):
        require_successful_parse(_failed_parse_result())


def test_ast_metadata_is_frozen() -> None:
    """`AstMetadata` should be immutable once constructed."""
    metadata = AstMetadata(relative_path="a.py")
    with pytest.raises(AttributeError):
        metadata.class_count = 99  # type: ignore[misc]
