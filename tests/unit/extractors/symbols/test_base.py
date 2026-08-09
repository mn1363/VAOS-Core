"""Unit tests for `src.extractors.symbols.base`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.symbols.base import (
    ExtractedSymbol,
    ExtractedSymbolKind,
    SymbolExtractionResult,
    SymbolExtractor,
    build_qualified_name,
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


def test_symbol_extractor_cannot_be_instantiated_directly() -> None:
    """The abstract `SymbolExtractor` Port must not be instantiable."""
    with pytest.raises(TypeError):
        SymbolExtractor()  # type: ignore[abstract]


def test_symbol_extraction_result_ok_builds_a_successful_result() -> None:
    """`SymbolExtractionResult.ok` should set `succeeded=True` and carry the symbols."""
    symbol = ExtractedSymbol(
        qualified_name="a.py::Foo",
        name="Foo",
        kind=ExtractedSymbolKind.CLASS,
        relative_path="a.py",
    )

    result = SymbolExtractionResult.ok(relative_path="a.py", symbols=[symbol])

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.symbols == (symbol,)
    assert result.error_message is None


def test_symbol_extraction_result_ok_defaults_to_no_symbols() -> None:
    """`SymbolExtractionResult.ok` should accept an omitted `symbols` sequence as empty."""
    result = SymbolExtractionResult.ok(relative_path="a.py")
    assert result.symbols == ()


def test_symbol_extraction_result_failed_builds_a_failed_result() -> None:
    """`SymbolExtractionResult.failed` should set `succeeded=False` and carry the error."""
    result = SymbolExtractionResult.failed(relative_path="a.py", error_message="went wrong")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.symbols == ()
    assert result.error_message == "went wrong"


def test_symbol_extraction_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    with pytest.raises(ValidationError):
        SymbolExtractionResult(relative_path="a.py", succeeded=True, error_message="unexpected")


def test_symbol_extraction_result_rejects_symbols_on_failure() -> None:
    """Constructing a failed result with symbols attached should raise."""
    symbol = ExtractedSymbol(
        qualified_name="a.py::Foo",
        name="Foo",
        kind=ExtractedSymbolKind.CLASS,
        relative_path="a.py",
    )
    with pytest.raises(ValidationError):
        SymbolExtractionResult(
            relative_path="a.py", succeeded=False, symbols=(symbol,), error_message="went wrong"
        )


def test_symbol_extraction_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        SymbolExtractionResult(relative_path="a.py", succeeded=False)


def test_require_successful_parse_returns_a_successful_result_unchanged() -> None:
    """`require_successful_parse` should pass a successful `ParseResult` through unchanged."""
    parse_result = _successful_parse_result()
    assert require_successful_parse(parse_result) is parse_result


def test_require_successful_parse_rejects_a_failed_result() -> None:
    """`require_successful_parse` should raise `ValidationError` for a failed `ParseResult`."""
    with pytest.raises(ValidationError):
        require_successful_parse(_failed_parse_result())


def test_build_qualified_name_without_owner() -> None:
    """`build_qualified_name` should join the path and name with `::` when there is no owner."""
    assert build_qualified_name(relative_path="a.py", name="foo") == "a.py::foo"


def test_build_qualified_name_with_owner() -> None:
    """`build_qualified_name` should interpose the owner, joined to the name with `.`."""
    assert (
        build_qualified_name(relative_path="a.py", name="bar", owner="Foo") == "a.py::Foo.bar"
    )


def test_extracted_symbol_is_frozen() -> None:
    """`ExtractedSymbol` should be immutable once constructed."""
    symbol = ExtractedSymbol(
        qualified_name="a.py::Foo",
        name="Foo",
        kind=ExtractedSymbolKind.CLASS,
        relative_path="a.py",
    )
    with pytest.raises(AttributeError):
        symbol.name = "Bar"  # type: ignore[misc]
