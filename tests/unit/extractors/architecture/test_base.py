"""Unit tests for `src.extractors.architecture.base`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.architecture.base import (
    ArchitectureExtractionResult,
    ArchitectureExtractor,
    PackageUnit,
    is_package_root_marker,
    require_successful_parse,
)
from src.parsers.base import FileMetadata, ParsedModule, ParseResult


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


def test_architecture_extractor_cannot_be_instantiated_directly() -> None:
    """The abstract `ArchitectureExtractor` Port must not be instantiable."""
    with pytest.raises(TypeError):
        ArchitectureExtractor()  # type: ignore[abstract]


def test_architecture_extraction_result_ok_builds_a_successful_result() -> None:
    """`ArchitectureExtractionResult.ok` should set `succeeded=True` and carry the unit."""
    unit = PackageUnit(relative_path="a.py", package_path=("a",))

    result = ArchitectureExtractionResult.ok(relative_path="a.py", unit=unit)

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.unit == unit
    assert result.error_message is None


def test_architecture_extraction_result_failed_builds_a_failed_result() -> None:
    """`ArchitectureExtractionResult.failed` should set `succeeded=False` and carry the error."""
    result = ArchitectureExtractionResult.failed(relative_path="a.py", error_message="no unit")

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.unit is None
    assert result.error_message == "no unit"


def test_architecture_extraction_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    unit = PackageUnit(relative_path="a.py", package_path=("a",))
    with pytest.raises(ValidationError):
        ArchitectureExtractionResult(
            relative_path="a.py", succeeded=True, unit=unit, error_message="unexpected"
        )


def test_architecture_extraction_result_requires_unit_on_success() -> None:
    """Constructing a successful result without a unit should raise."""
    with pytest.raises(ValidationError):
        ArchitectureExtractionResult(relative_path="a.py", succeeded=True, unit=None)


def test_architecture_extraction_result_rejects_unit_on_failure() -> None:
    """Constructing a failed result with a unit attached should raise."""
    unit = PackageUnit(relative_path="a.py", package_path=("a",))
    with pytest.raises(ValidationError):
        ArchitectureExtractionResult(
            relative_path="a.py", succeeded=False, unit=unit, error_message="went wrong"
        )


def test_architecture_extraction_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        ArchitectureExtractionResult(relative_path="a.py", succeeded=False)


def test_require_successful_parse_returns_a_successful_result_unchanged() -> None:
    """`require_successful_parse` should pass a successful `ParseResult` through unchanged."""
    parse_result = _successful_parse_result()
    assert require_successful_parse(parse_result) is parse_result


def test_require_successful_parse_rejects_a_failed_result() -> None:
    """`require_successful_parse` should raise `ValidationError` for a failed `ParseResult`."""
    with pytest.raises(ValidationError):
        require_successful_parse(_failed_parse_result())


def test_is_package_root_marker_recognizes_init_py() -> None:
    """`is_package_root_marker` should recognize `__init__.py` at any depth."""
    assert is_package_root_marker("src/extractors/architecture/__init__.py") is True


def test_is_package_root_marker_recognizes_a_bare_filename() -> None:
    """`is_package_root_marker` should recognize a marker filename with no directory prefix."""
    assert is_package_root_marker("__init__.py") is True


def test_is_package_root_marker_rejects_an_ordinary_file() -> None:
    """`is_package_root_marker` should reject a file that is not a package-root marker."""
    assert is_package_root_marker("src/extractors/architecture/base.py") is False


def test_package_unit_is_frozen() -> None:
    """`PackageUnit` should be immutable once constructed."""
    unit = PackageUnit(relative_path="a.py", package_path=("a",))
    with pytest.raises(AttributeError):
        unit.relative_path = "b.py"  # type: ignore[misc]


def test_package_unit_defaults_to_no_declared_modules() -> None:
    """`PackageUnit` should default `declared_modules` to an empty tuple."""
    unit = PackageUnit(relative_path="a.py", package_path=("a",))
    assert unit.declared_modules == ()
    assert unit.is_package_root is False


def test_package_unit_carries_declared_modules() -> None:
    """`PackageUnit` should carry through nested module declarations."""
    module = ParsedModule(name="inner")
    unit = PackageUnit(
        relative_path="a.py", package_path=("a",), declared_modules=(module,)
    )
    assert unit.declared_modules == (module,)
