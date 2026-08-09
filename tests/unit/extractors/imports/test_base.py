"""Unit tests for `src.extractors.imports.base`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.imports.base import (
    DependencyEdge,
    ImportExtractionResult,
    ImportExtractor,
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


def test_import_extractor_cannot_be_instantiated_directly() -> None:
    """The abstract `ImportExtractor` Port must not be instantiable."""
    with pytest.raises(TypeError):
        ImportExtractor()  # type: ignore[abstract]


def test_import_extraction_result_ok_builds_a_successful_result() -> None:
    """`ImportExtractionResult.ok` should set `succeeded=True` and carry the edges."""
    edge = DependencyEdge(source_path="a.py", target_module="os")

    result = ImportExtractionResult.ok(relative_path="a.py", edges=[edge])

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.edges == (edge,)
    assert result.error_message is None


def test_import_extraction_result_ok_defaults_to_no_edges() -> None:
    """`ImportExtractionResult.ok` should accept an omitted `edges` sequence as empty."""
    result = ImportExtractionResult.ok(relative_path="a.py")
    assert result.edges == ()


def test_import_extraction_result_failed_builds_a_failed_result() -> None:
    """`ImportExtractionResult.failed` should set `succeeded=False` and carry the error."""
    result = ImportExtractionResult.failed(relative_path="a.py", error_message="went wrong")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.edges == ()
    assert result.error_message == "went wrong"


def test_import_extraction_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    with pytest.raises(ValidationError):
        ImportExtractionResult(relative_path="a.py", succeeded=True, error_message="unexpected")


def test_import_extraction_result_rejects_edges_on_failure() -> None:
    """Constructing a failed result with edges attached should raise."""
    edge = DependencyEdge(source_path="a.py", target_module="os")
    with pytest.raises(ValidationError):
        ImportExtractionResult(
            relative_path="a.py", succeeded=False, edges=(edge,), error_message="went wrong"
        )


def test_import_extraction_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        ImportExtractionResult(relative_path="a.py", succeeded=False)


def test_require_successful_parse_returns_a_successful_result_unchanged() -> None:
    """`require_successful_parse` should pass a successful `ParseResult` through unchanged."""
    parse_result = _successful_parse_result()
    assert require_successful_parse(parse_result) is parse_result


def test_require_successful_parse_rejects_a_failed_result() -> None:
    """`require_successful_parse` should raise `ValidationError` for a failed `ParseResult`."""
    with pytest.raises(ValidationError):
        require_successful_parse(_failed_parse_result())


def test_dependency_edge_is_frozen() -> None:
    """`DependencyEdge` should be immutable once constructed."""
    edge = DependencyEdge(source_path="a.py", target_module="os")
    with pytest.raises(AttributeError):
        edge.target_module = "sys"  # type: ignore[misc]


def test_dependency_edge_defaults() -> None:
    """`DependencyEdge` should default its optional fields sensibly."""
    edge = DependencyEdge(source_path="a.py", target_module="os")

    assert edge.imported_names == ()
    assert edge.alias is None
    assert edge.is_internal is False
    assert edge.line_number == 0


def test_dependency_edge_carries_full_import_details() -> None:
    """`DependencyEdge` should carry through every field when given."""
    edge = DependencyEdge(
        source_path="a.py",
        target_module=".widgets",
        imported_names=("Widget",),
        alias="w",
        is_internal=True,
        line_number=3,
    )

    assert edge.source_path == "a.py"
    assert edge.target_module == ".widgets"
    assert edge.imported_names == ("Widget",)
    assert edge.alias == "w"
    assert edge.is_internal is True
    assert edge.line_number == 3
