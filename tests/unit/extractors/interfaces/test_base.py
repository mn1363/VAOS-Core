"""Unit tests for `src.extractors.interfaces.base`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.interfaces.base import (
    ExtractedInterface,
    InterfaceExtractionResult,
    InterfaceExtractor,
    InterfaceOrigin,
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


def test_interface_extractor_cannot_be_instantiated_directly() -> None:
    """The abstract `InterfaceExtractor` Port must not be instantiable."""
    with pytest.raises(TypeError):
        InterfaceExtractor()  # type: ignore[abstract]


def test_interface_extraction_result_ok_builds_a_successful_result() -> None:
    """`InterfaceExtractionResult.ok` should set `succeeded=True` and carry the interfaces."""
    interface = ExtractedInterface(
        name="Comparable", origin=InterfaceOrigin.ABSTRACT_CLASS, relative_path="a.py"
    )

    result = InterfaceExtractionResult.ok(relative_path="a.py", interfaces=[interface])

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.interfaces == (interface,)
    assert result.error_message is None


def test_interface_extraction_result_ok_defaults_to_no_interfaces() -> None:
    """`InterfaceExtractionResult.ok` should accept an omitted `interfaces` sequence as empty."""
    result = InterfaceExtractionResult.ok(relative_path="a.py")
    assert result.interfaces == ()


def test_interface_extraction_result_failed_builds_a_failed_result() -> None:
    """`InterfaceExtractionResult.failed` should set `succeeded=False` and carry the error."""
    result = InterfaceExtractionResult.failed(relative_path="a.py", error_message="went wrong")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.interfaces == ()
    assert result.error_message == "went wrong"


def test_interface_extraction_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    with pytest.raises(ValidationError):
        InterfaceExtractionResult(
            relative_path="a.py", succeeded=True, error_message="unexpected"
        )


def test_interface_extraction_result_rejects_interfaces_on_failure() -> None:
    """Constructing a failed result with interfaces attached should raise."""
    interface = ExtractedInterface(
        name="Comparable", origin=InterfaceOrigin.ABSTRACT_CLASS, relative_path="a.py"
    )
    with pytest.raises(ValidationError):
        InterfaceExtractionResult(
            relative_path="a.py",
            succeeded=False,
            interfaces=(interface,),
            error_message="went wrong",
        )


def test_interface_extraction_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        InterfaceExtractionResult(relative_path="a.py", succeeded=False)


def test_require_successful_parse_returns_a_successful_result_unchanged() -> None:
    """`require_successful_parse` should pass a successful `ParseResult` through unchanged."""
    parse_result = _successful_parse_result()
    assert require_successful_parse(parse_result) is parse_result


def test_require_successful_parse_rejects_a_failed_result() -> None:
    """`require_successful_parse` should raise `ValidationError` for a failed `ParseResult`."""
    with pytest.raises(ValidationError):
        require_successful_parse(_failed_parse_result())


def test_extracted_interface_is_frozen() -> None:
    """`ExtractedInterface` should be immutable once constructed."""
    interface = ExtractedInterface(
        name="Comparable", origin=InterfaceOrigin.ABSTRACT_CLASS, relative_path="a.py"
    )
    with pytest.raises(AttributeError):
        interface.name = "Other"  # type: ignore[misc]


def test_extracted_interface_defaults() -> None:
    """`ExtractedInterface` should default its optional fields sensibly."""
    interface = ExtractedInterface(
        name="Comparable", origin=InterfaceOrigin.TRAIT, relative_path="a.py"
    )

    assert interface.method_signatures == ()
    assert interface.base_interfaces == ()
    assert interface.line_number == 0


@pytest.mark.parametrize(
    "origin",
    [InterfaceOrigin.LANGUAGE_INTERFACE, InterfaceOrigin.TRAIT, InterfaceOrigin.ABSTRACT_CLASS],
)
def test_interface_origin_members_round_trip(origin: InterfaceOrigin) -> None:
    """Every `InterfaceOrigin` member should be usable as an `ExtractedInterface.origin`."""
    interface = ExtractedInterface(name="X", origin=origin, relative_path="a.py")
    assert interface.origin is origin
