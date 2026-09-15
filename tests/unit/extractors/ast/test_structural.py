"""Unit tests for `src.extractors.ast.structural`.

Each of the five language-specific cases below parses a small, real source snippet with one of
the five existing concrete `Parser` implementations, then runs the resulting real `ParseResult`
through a single, shared `StructuralAstExtractor` instance -- proving one implementation handles
every language, not five per-language variants. Every expected count in this file was obtained
by running the real parser and the real extractor together and reading off the result -- none is
hand-derived from the source snippet alone.
"""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.ast.base import AstExtractor
from src.extractors.ast.structural import StructuralAstExtractor
from src.parsers.base import ParseResult
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser


def _failed_parse_result(relative_path: str = "a.py") -> ParseResult:
    """Build a minimal, failed `ParseResult` for use in extraction tests."""
    return ParseResult.failed(
        relative_path=relative_path, language=SourceLanguage.PYTHON, error_message="bad syntax"
    )


# --- one implementation, five languages, all real parser output --------------------------


def test_python_mixed_file_exercises_every_count_field() -> None:
    """A single Python file exercising every `AstMetadata` field at once, via the real parser.

    Two classes (one documented, one not) with three methods between them (one async), two
    free functions (one documented, one async), two imports, an `__all__` export list of two
    names, and no nested modules (Python has no such construct).
    """
    content = (
        "import os\n"
        "from typing import List\n"
        "\n"
        '__all__ = ["Foo", "helper"]\n'
        "\n"
        "\n"
        "class Foo:\n"
        '    """A documented class."""\n'
        "\n"
        "    def method_a(self):\n"
        "        pass\n"
        "\n"
        "    async def method_b(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "class Bar:\n"
        "    def undocumented_method(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "def helper():\n"
        '    """A documented function."""\n'
        "    pass\n"
        "\n"
        "\n"
        "async def async_helper():\n"
        "    pass\n"
    )
    parse_result = PythonParser().parse(relative_path="mixed.py", content=content)
    result = StructuralAstExtractor().extract(parse_result)

    assert result.succeeded is True
    metadata = result.metadata
    assert metadata is not None
    assert metadata.relative_path == "mixed.py"
    assert metadata.class_count == 2
    assert metadata.function_count == 2
    assert metadata.method_count == 3
    assert metadata.import_count == 2
    assert metadata.export_count == 2
    assert metadata.symbol_count == 7
    assert metadata.module_count == 0
    assert metadata.async_function_count == 2
    assert metadata.documented_class_count == 1
    assert metadata.documented_function_count == 1
    assert metadata.line_count == 28


def test_rust_class_and_method_docstrings_are_counted() -> None:
    """A real documented `struct`/`impl`/`async fn`, parsed by the real `RustParser`, counts
    correctly -- including the method's own `///` doc comment, which `RustParser` does capture."""
    content = (
        "/// A documented struct.\n"
        "struct Widget {\n"
        "    name: String,\n"
        "}\n"
        "\n"
        "impl Widget {\n"
        "    /// A documented method.\n"
        "    fn new() -> Self {\n"
        "        Widget { name: String::new() }\n"
        "    }\n"
        "}\n"
        "\n"
        "async fn fetch_data() {}\n"
    )
    parse_result = RustParser().parse(relative_path="widget.rs", content=content)
    result = StructuralAstExtractor().extract(parse_result)

    assert result.succeeded is True
    metadata = result.metadata
    assert metadata is not None
    assert metadata.class_count == 1
    assert metadata.function_count == 1
    assert metadata.method_count == 1
    assert metadata.symbol_count == 3
    assert metadata.module_count == 0
    assert metadata.async_function_count == 1
    assert metadata.documented_class_count == 1
    assert metadata.documented_function_count == 1
    assert metadata.line_count == 13


def test_go_documented_source_still_produces_zero_documented_counts() -> None:
    """Known parser limitation, explicitly asserted: `GoParser` never populates `docstring` on
    any `ParsedFunction`/`ParsedClass`, so `documented_class_count`/`documented_function_count`
    are `0` here even though `Widget` and `NewWidget` are genuinely documented with real `//`
    doc comments in the source. This is not a defect in `StructuralAstExtractor` -- there is
    nothing for it to count, since the data was never carried past `GoParser` in the first
    place. Fixing it would mean changing the frozen `GoParser`, which is out of scope here."""
    content = (
        "package main\n"
        "\n"
        "// Widget is a documented struct.\n"
        "type Widget struct {\n"
        "\tName string\n"
        "}\n"
        "\n"
        "// NewWidget is a documented constructor function.\n"
        "func NewWidget() *Widget {\n"
        "\treturn &Widget{}\n"
        "}\n"
        "\n"
        "func (w *Widget) Greet() string {\n"
        '\treturn "hello"\n'
        "}\n"
    )
    parse_result = GoParser().parse(relative_path="widget.go", content=content)
    result = StructuralAstExtractor().extract(parse_result)

    assert result.succeeded is True
    metadata = result.metadata
    assert metadata is not None
    assert metadata.class_count == 1
    assert metadata.function_count == 1
    assert metadata.method_count == 1
    assert metadata.module_count == 1
    assert metadata.async_function_count == 0
    # The known Go limitation, asserted explicitly rather than merely allowed to pass silently:
    assert metadata.documented_class_count == 0
    assert metadata.documented_function_count == 0


def test_typescript_class_and_free_function_docstrings_are_counted() -> None:
    """A real documented class and free function, parsed by the real `TypeScriptParser`.

    `TypeScriptParser` captures JSDoc for classes and free functions but never for in-class
    methods (`_build_method` never sets `docstring`) -- `greet`'s own JSDoc comment is present
    in the source but is not reflected in `documented_function_count`, which counts only the
    documented free function `helper`."""
    content = (
        "/**\n"
        " * A documented class.\n"
        " */\n"
        "class Widget {\n"
        "  /**\n"
        "   * A documented method (JSDoc on methods is not captured by this parser).\n"
        "   */\n"
        "  greet(): string {\n"
        '    return "hello";\n'
        "  }\n"
        "\n"
        "  async fetchData(): Promise<void> {}\n"
        "}\n"
        "\n"
        "/**\n"
        " * A documented free function.\n"
        " */\n"
        "export function helper(): void {}\n"
    )
    parse_result = TypeScriptParser().parse(relative_path="widget.ts", content=content)
    result = StructuralAstExtractor().extract(parse_result)

    assert result.succeeded is True
    metadata = result.metadata
    assert metadata is not None
    assert metadata.class_count == 1
    assert metadata.function_count == 1
    assert metadata.method_count == 2
    assert metadata.export_count == 1
    assert metadata.async_function_count == 1
    assert metadata.documented_class_count == 1
    assert metadata.documented_function_count == 1
    assert metadata.line_count == 18


def test_cpp_class_and_free_function_docstrings_are_counted() -> None:
    """A real documented class and free function, parsed by the real `CppParser`.

    `CppParser` captures `///` doc comments for classes and free functions but never for
    in-class methods (`_build_method` never sets `docstring`) -- `greet`'s own `///` comment is
    present in the source but is not reflected in `documented_function_count`, which counts only
    the documented free function `helper`."""
    content = (
        "/// A documented class.\n"
        "class Widget {\n"
        "public:\n"
        "    /// A documented method.\n"
        "    void greet() {\n"
        "        return;\n"
        "    }\n"
        "};\n"
        "\n"
        "/// A documented free function.\n"
        "void helper() {}\n"
    )
    parse_result = CppParser().parse(relative_path="widget.cpp", content=content)
    result = StructuralAstExtractor().extract(parse_result)

    assert result.succeeded is True
    metadata = result.metadata
    assert metadata is not None
    assert metadata.class_count == 1
    assert metadata.function_count == 1
    assert metadata.method_count == 1
    assert metadata.async_function_count == 0
    assert metadata.documented_class_count == 1
    assert metadata.documented_function_count == 1
    assert metadata.line_count == 11


def test_single_extractor_instance_handles_all_five_languages() -> None:
    """One `StructuralAstExtractor` instance, reused, succeeds against all five parsers."""
    extractor = StructuralAstExtractor()
    cases: tuple[tuple[ParseResult, int], ...] = (
        (PythonParser().parse(relative_path="a.py", content="def f():\n    pass\n"), 1),
        (RustParser().parse(relative_path="a.rs", content="fn f() {}\n"), 1),
        (GoParser().parse(relative_path="a.go", content="package main\n\nfunc f() {}\n"), 1),
        (TypeScriptParser().parse(relative_path="a.ts", content="function f(): void {}\n"), 1),
        (CppParser().parse(relative_path="a.cpp", content="void f() {}\n"), 1),
    )
    for parse_result, expected_function_count in cases:
        result = extractor.extract(parse_result)
        assert result.succeeded is True
        assert result.metadata is not None
        assert result.metadata.function_count == expected_function_count


# --- empty input, documentation edge cases --------------------------------------------------


def test_empty_file_produces_all_zero_counts() -> None:
    """A file with no content produces a successful result with every count at `0`."""
    parse_result = PythonParser().parse(relative_path="empty.py", content="")
    result = StructuralAstExtractor().extract(parse_result)

    assert result.succeeded is True
    metadata = result.metadata
    assert metadata is not None
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


def test_empty_docstring_still_counts_as_documented() -> None:
    """A function whose docstring literal is empty (`\"\"\" \"\"\"`) still counts as documented.

    `ast.get_docstring` returns `""` for this case -- not `None` -- and the correct test is
    `docstring is not None`, not a truthiness check, which would wrongly treat an empty-but-
    present docstring as undocumented."""
    parse_result = PythonParser().parse(
        relative_path="a.py", content='def foo():\n    """ """\n    pass\n'
    )
    result = StructuralAstExtractor().extract(parse_result)

    assert result.succeeded is True
    metadata = result.metadata
    assert metadata is not None
    assert metadata.documented_function_count == 1


# --- failure behavior ------------------------------------------------------------------------


def test_failed_parse_result_raises_validation_error() -> None:
    """A failed `ParseResult` raises `ValidationError` via `require_successful_parse`, unchanged."""
    with pytest.raises(ValidationError):
        StructuralAstExtractor().extract(_failed_parse_result())


def test_structural_ast_extractor_is_an_ast_extractor() -> None:
    """`StructuralAstExtractor` is a genuine `AstExtractor`, not just structurally similar."""
    assert isinstance(StructuralAstExtractor(), AstExtractor)
