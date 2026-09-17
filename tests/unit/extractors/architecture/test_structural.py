"""Unit tests for `src.extractors.architecture.structural`.

Each language-specific case below parses a small, real source snippet with one of the existing
concrete `Parser` implementations, then runs the resulting real `ParseResult` through a single,
shared `StructuralArchitectureExtractor` instance -- proving one implementation handles every
language, not one per-language variant.
"""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.architecture.base import ArchitectureExtractor, PackageUnit
from src.extractors.architecture.structural import StructuralArchitectureExtractor
from src.parsers.base import ParseResult
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser


def _failed_parse_result(relative_path: str = "a.py") -> ParseResult:
    """Build a minimal, failed `ParseResult` for use in extraction tests."""
    return ParseResult.failed(
        relative_path=relative_path, language=SourceLanguage.PYTHON, error_message="bad syntax"
    )


# --- package_path derivation ------------------------------------------------------------------


def test_root_level_file_produces_empty_package_path() -> None:
    """A file with no directory component produces `package_path == ()`."""
    parse_result = PythonParser().parse(relative_path="main.py", content="x = 1\n")
    result = StructuralArchitectureExtractor().extract(parse_result)

    assert result.succeeded is True
    unit = result.unit
    assert unit is not None
    assert unit.package_path == ()


def test_nested_path_produces_full_directory_segments() -> None:
    """A nested file's `package_path` is every directory segment, in order."""
    parse_result = PythonParser().parse(
        relative_path="src/extractors/architecture/base.py", content="x = 1\n"
    )
    result = StructuralArchitectureExtractor().extract(parse_result)

    unit = result.unit
    assert unit is not None
    assert unit.package_path == ("src", "extractors", "architecture")


# --- is_package_root, across languages ----------------------------------------------------------


def test_python_init_py_is_a_package_root() -> None:
    """A Python `__init__.py`, parsed by the real `PythonParser`, is a package root."""
    parse_result = PythonParser().parse(relative_path="pkg/__init__.py", content="")
    result = StructuralArchitectureExtractor().extract(parse_result)

    unit = result.unit
    assert unit is not None
    assert unit.is_package_root is True


def test_python_init_pyi_is_a_package_root() -> None:
    """A Python `__init__.pyi` stub, parsed by the real `PythonParser`, is a package root."""
    parse_result = PythonParser().parse(relative_path="pkg/__init__.pyi", content="")
    result = StructuralArchitectureExtractor().extract(parse_result)

    unit = result.unit
    assert unit is not None
    assert unit.is_package_root is True


def test_rust_mod_rs_is_a_package_root() -> None:
    """A Rust `mod.rs`, parsed by the real `RustParser`, is a package root."""
    parse_result = RustParser().parse(relative_path="pkg/mod.rs", content="fn f() {}\n")
    result = StructuralArchitectureExtractor().extract(parse_result)

    unit = result.unit
    assert unit is not None
    assert unit.is_package_root is True


def test_typescript_index_ts_is_a_package_root() -> None:
    """A TypeScript `index.ts`, parsed by the real `TypeScriptParser`, is a package root."""
    parse_result = TypeScriptParser().parse(
        relative_path="pkg/index.ts", content="export const x = 1;\n"
    )
    result = StructuralArchitectureExtractor().extract(parse_result)

    unit = result.unit
    assert unit is not None
    assert unit.is_package_root is True


def test_ordinary_file_is_not_a_package_root() -> None:
    """An ordinary, non-marker file is not a package root."""
    parse_result = PythonParser().parse(relative_path="pkg/widget.py", content="x = 1\n")
    result = StructuralArchitectureExtractor().extract(parse_result)

    unit = result.unit
    assert unit is not None
    assert unit.is_package_root is False


# --- declared_modules pass-through --------------------------------------------------------------


def test_go_file_carries_its_declared_package_module() -> None:
    """A real Go file's `package` clause, parsed by the real `GoParser`, is passed straight
    through to `declared_modules` -- no Go-specific package-root inference is performed here;
    `is_package_root` still comes only from `is_package_root_marker`, which has no Go filename
    entry, matching the frozen contract exactly."""
    parse_result = GoParser().parse(
        relative_path="pkg/widget.go", content="package widget\n\nfunc F() {}\n"
    )
    result = StructuralArchitectureExtractor().extract(parse_result)

    unit = result.unit
    assert unit is not None
    assert len(unit.declared_modules) == 1
    assert unit.declared_modules[0].name == "widget"
    assert unit.declared_modules == parse_result.modules
    assert unit.is_package_root is False


def test_python_file_has_no_declared_modules() -> None:
    """`PythonParser` never produces a `ParsedModule` (Python has no such construct), so
    `declared_modules` is empty for a real Python file -- existing parser behavior, preserved
    exactly, not compensated for here."""
    parse_result = PythonParser().parse(
        relative_path="pkg/widget.py", content="class Widget:\n    pass\n"
    )

    assert parse_result.modules == ()

    result = StructuralArchitectureExtractor().extract(parse_result)
    unit = result.unit
    assert unit is not None
    assert unit.declared_modules == ()


def test_declared_modules_preserves_source_order() -> None:
    """Multiple declared modules in one file are passed through in their original source
    order, not re-sorted."""
    content = "mod zeta {}\nmod alpha {}\nmod middle {}\n"
    parse_result = RustParser().parse(relative_path="pkg/mod.rs", content=content)
    result = StructuralArchitectureExtractor().extract(parse_result)

    unit = result.unit
    assert unit is not None
    assert [module.name for module in unit.declared_modules] == ["zeta", "alpha", "middle"]
    assert unit.declared_modules == parse_result.modules


# --- empty ParseResult ---------------------------------------------------------------------------


def test_empty_file_still_produces_a_valid_unit() -> None:
    """A file with no content at all -- an "empty" successful `ParseResult`, with every
    parsed-content field at its default `()` -- still produces a successful result with an
    empty `package_path`, no package-root marker, and no declared modules."""
    parse_result = PythonParser().parse(relative_path="empty.py", content="")

    assert parse_result.classes == ()
    assert parse_result.functions == ()
    assert parse_result.modules == ()

    result = StructuralArchitectureExtractor().extract(parse_result)

    assert result.succeeded is True
    unit = result.unit
    assert unit is not None
    assert unit.relative_path == "empty.py"
    assert unit.package_path == ()
    assert unit.is_package_root is False
    assert unit.declared_modules == ()


# --- exact field mapping ---------------------------------------------------------------------


def test_exact_package_unit_field_mapping() -> None:
    """Every `PackageUnit` field, asserted together against one real, non-trivial input."""
    parse_result = RustParser().parse(
        relative_path="src/widgets/mod.rs", content="mod inner {}\n"
    )
    result = StructuralArchitectureExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.relative_path == "src/widgets/mod.rs"
    unit = result.unit
    assert unit == PackageUnit(
        relative_path="src/widgets/mod.rs",
        package_path=("src", "widgets"),
        is_package_root=True,
        declared_modules=parse_result.modules,
    )


# --- failure behavior ------------------------------------------------------------------------


def test_failed_parse_result_raises_validation_error() -> None:
    """A failed `ParseResult` raises `ValidationError` via `require_successful_parse`, unchanged."""
    with pytest.raises(ValidationError):
        StructuralArchitectureExtractor().extract(_failed_parse_result())


def test_structural_architecture_extractor_is_an_architecture_extractor() -> None:
    """`StructuralArchitectureExtractor` is a genuine `ArchitectureExtractor`, not just
    structurally similar."""
    assert isinstance(StructuralArchitectureExtractor(), ArchitectureExtractor)
