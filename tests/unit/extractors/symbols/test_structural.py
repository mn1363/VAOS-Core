"""Unit tests for `src.extractors.symbols.structural`.

Each of the five language-specific cases below parses a small, real source snippet with one of
the five existing concrete `Parser` implementations, then runs the resulting real `ParseResult`
through a single, shared `StructuralSymbolExtractor` instance -- proving one implementation
handles every language, not five per-language variants. Every expected value in this file was
obtained by running the real parser and the real extractor together and reading off the
result -- none is hand-derived from the source snippet alone.
"""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.symbols.base import ExtractedSymbolKind, SymbolExtractor
from src.extractors.symbols.structural import StructuralSymbolExtractor
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


def test_python_class_and_function_are_extracted() -> None:
    """A real class and free function, parsed by the real `PythonParser`, map exactly."""
    parse_result = PythonParser().parse(
        relative_path="a.py", content="class Foo:\n    pass\n\n\ndef helper():\n    pass\n"
    )
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert [(s.kind, s.name) for s in result.symbols] == [
        (ExtractedSymbolKind.CLASS, "Foo"),
        (ExtractedSymbolKind.FUNCTION, "helper"),
    ]


def test_rust_struct_method_function_and_constant_are_extracted() -> None:
    """A real struct/impl/fn/const, parsed by the real `RustParser`, map exactly -- and prove
    the locked output order (classes, methods, functions, constants) end to end."""
    content = (
        "struct Widget {\n"
        "    name: String,\n"
        "}\n"
        "\n"
        "impl Widget {\n"
        "    fn greet(&self) {}\n"
        "}\n"
        "\n"
        "fn top_level_fn() {}\n"
        "\n"
        "const MAX: u32 = 10;\n"
    )
    parse_result = RustParser().parse(relative_path="a.rs", content=content)
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert [(s.kind, s.name, s.line_number) for s in result.symbols] == [
        (ExtractedSymbolKind.CLASS, "Widget", 1),
        (ExtractedSymbolKind.METHOD, "greet", 6),
        (ExtractedSymbolKind.FUNCTION, "top_level_fn", 9),
        (ExtractedSymbolKind.CONSTANT, "MAX", 11),
    ]
    assert result.symbols[0].qualified_name == "a.rs::Widget"
    assert result.symbols[1].qualified_name == "a.rs::Widget.greet"
    assert result.symbols[2].qualified_name == "a.rs::top_level_fn"
    assert result.symbols[3].qualified_name == "a.rs::MAX"


def test_go_constant_is_extracted() -> None:
    """A real package-level `const`, parsed by the real `GoParser`, maps exactly."""
    parse_result = GoParser().parse(
        relative_path="a.go", content="package main\n\nconst TopLevel = 10\n\nfunc doWork() {}\n"
    )
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    constant = next(s for s in result.symbols if s.kind == ExtractedSymbolKind.CONSTANT)
    assert constant.name == "TopLevel"
    assert constant.qualified_name == "a.go::TopLevel"
    assert constant.line_number == 3


def test_typescript_class_with_method_is_extracted() -> None:
    """A real class with one method, parsed by the real `TypeScriptParser`, maps exactly."""
    parse_result = TypeScriptParser().parse(
        relative_path="a.ts", content="class Widget {\n  greet(): void {}\n}\n"
    )
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert [(s.kind, s.name) for s in result.symbols] == [
        (ExtractedSymbolKind.CLASS, "Widget"),
        (ExtractedSymbolKind.METHOD, "greet"),
    ]
    assert result.symbols[1].qualified_name == "a.ts::Widget.greet"


def test_cpp_class_and_function_are_extracted() -> None:
    """A real class with a method and a free function, parsed by the real `CppParser`, map
    exactly."""
    content = "class Widget {\npublic:\n    void greet() {}\n};\n\nvoid helper() {}\n"
    parse_result = CppParser().parse(relative_path="a.cpp", content=content)
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert [(s.kind, s.name) for s in result.symbols] == [
        (ExtractedSymbolKind.CLASS, "Widget"),
        (ExtractedSymbolKind.METHOD, "greet"),
        (ExtractedSymbolKind.FUNCTION, "helper"),
    ]


def test_single_extractor_instance_handles_all_five_languages() -> None:
    """One `StructuralSymbolExtractor` instance, reused, succeeds against all five parsers."""
    extractor = StructuralSymbolExtractor()
    cases: tuple[ParseResult, ...] = (
        PythonParser().parse(relative_path="a.py", content="def f():\n    pass\n"),
        RustParser().parse(relative_path="a.rs", content="fn f() {}\n"),
        GoParser().parse(relative_path="a.go", content="package main\n\nfunc f() {}\n"),
        TypeScriptParser().parse(relative_path="a.ts", content="function f(): void {}\n"),
        CppParser().parse(relative_path="a.cpp", content="void f() {}\n"),
    )
    for parse_result in cases:
        result = extractor.extract(parse_result)
        assert result.succeeded is True
        assert len(result.symbols) == 1
        assert result.symbols[0].kind == ExtractedSymbolKind.FUNCTION
        assert result.symbols[0].name == "f"


# --- required case 1: class + methods + top-level function ---------------------------------


def test_class_with_methods_and_top_level_function() -> None:
    """A class with two methods plus a free function, in the locked class-then-method-then-
    function order, with correctly qualified names."""
    content = (
        "class Foo:\n"
        "    def method_a(self):\n"
        "        pass\n"
        "\n"
        "    def method_b(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "def helper():\n"
        "    pass\n"
    )
    parse_result = PythonParser().parse(relative_path="a.py", content=content)
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert [(s.kind, s.name, s.qualified_name, s.line_number) for s in result.symbols] == [
        (ExtractedSymbolKind.CLASS, "Foo", "a.py::Foo", 1),
        (ExtractedSymbolKind.METHOD, "method_a", "a.py::Foo.method_a", 2),
        (ExtractedSymbolKind.METHOD, "method_b", "a.py::Foo.method_b", 5),
        (ExtractedSymbolKind.FUNCTION, "helper", "a.py::helper", 9),
    ]


# --- required case 2: constants from a CONSTANT-emitting parser ----------------------------


def test_constants_from_a_constant_emitting_parser() -> None:
    """A real top-level `const`, parsed by the real `GoParser` (one of the three parsers that
    emit `SymbolKind.CONSTANT`), is extracted with kind `CONSTANT`."""
    parse_result = GoParser().parse(
        relative_path="a.go", content="package main\n\nconst TopLevel = 10\n"
    )
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.symbols) == 1
    assert result.symbols[0].kind == ExtractedSymbolKind.CONSTANT
    assert result.symbols[0].name == "TopLevel"
    assert result.symbols[0].qualified_name == "a.go::TopLevel"
    assert result.symbols[0].line_number == 3


# --- required case 3: VARIABLE is not emitted as CONSTANT ------------------------------------


def test_variable_is_not_emitted_as_constant() -> None:
    """A real `let` declaration (kind `VARIABLE` at the parser layer) is never extracted; only
    the real `const` declaration (kind `CONSTANT`) is."""
    parse_result = TypeScriptParser().parse(
        relative_path="a.ts", content="let x = 1;\nconst y = 2;\n"
    )
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    names = [s.name for s in result.symbols]
    assert "x" not in names
    assert len(result.symbols) == 1
    assert result.symbols[0].kind == ExtractedSymbolKind.CONSTANT
    assert result.symbols[0].name == "y"


# --- required case 4: empty ParseResult -------------------------------------------------------


def test_empty_parse_result_produces_empty_symbols() -> None:
    """A file with no classes, functions, or constants produces a successful, empty result."""
    parse_result = PythonParser().parse(relative_path="empty.py", content="")
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.symbols == ()


# --- required case 5: failed ParseResult / ValidationError -----------------------------------


def test_failed_parse_result_raises_validation_error() -> None:
    """A failed `ParseResult` raises `ValidationError` via `require_successful_parse`, unchanged."""
    with pytest.raises(ValidationError):
        StructuralSymbolExtractor().extract(_failed_parse_result())


# --- required case 6: duplicate method names in different classes ----------------------------


def test_duplicate_method_names_in_different_classes_produce_different_qualified_names() -> None:
    """The same method name, defined on two different classes, produces two distinct
    `ExtractedSymbol` entries -- disambiguated by `qualified_name`, not merged."""
    content = (
        "class Foo:\n"
        "    def run(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "class Bar:\n"
        "    def run(self):\n"
        "        pass\n"
    )
    parse_result = PythonParser().parse(relative_path="a.py", content=content)
    result = StructuralSymbolExtractor().extract(parse_result)

    methods = [s for s in result.symbols if s.kind == ExtractedSymbolKind.METHOD]
    assert len(methods) == 2
    assert methods[0].name == "run"
    assert methods[1].name == "run"
    assert methods[0].qualified_name == "a.py::Foo.run"
    assert methods[1].qualified_name == "a.py::Bar.run"
    assert methods[0].qualified_name != methods[1].qualified_name


# --- required case 7: class with zero methods -------------------------------------------------


def test_class_with_zero_methods() -> None:
    """A class with no methods produces exactly one `CLASS` entry and no `METHOD` entries."""
    parse_result = PythonParser().parse(relative_path="a.py", content="class Empty:\n    pass\n")
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.symbols) == 1
    assert result.symbols[0].kind == ExtractedSymbolKind.CLASS
    assert result.symbols[0].name == "Empty"


# --- required case 8: deterministic repeated extraction ---------------------------------------


def test_deterministic_repeated_extraction() -> None:
    """Extracting the same `ParseResult` twice, with the same instance, produces equal results."""
    parse_result = PythonParser().parse(
        relative_path="a.py", content="class Foo:\n    def m(self):\n        pass\n"
    )
    extractor = StructuralSymbolExtractor()

    first = extractor.extract(parse_result)
    second = extractor.extract(parse_result)

    assert first == second
    assert first.symbols == second.symbols


# --- duplicates, general -----------------------------------------------------------------------


def test_duplicate_top_level_functions_are_preserved() -> None:
    """The same free function, defined twice, produces two entries -- not merged into one.

    Each occurrence is a genuinely distinct definition at its own source line, so the two
    entries correctly differ in `line_number`; what this proves is that neither is dropped as a
    "duplicate" of the other."""
    parse_result = PythonParser().parse(
        relative_path="a.py", content="def helper():\n    pass\n\n\ndef helper():\n    pass\n"
    )
    result = StructuralSymbolExtractor().extract(parse_result)

    assert len(result.symbols) == 2
    assert [s.name for s in result.symbols] == ["helper", "helper"]
    assert [s.line_number for s in result.symbols] == [1, 5]


# --- known parser-level CONSTANT limitations, explicitly asserted ----------------------------


def test_python_never_extracts_constants_due_to_parser_limitation() -> None:
    """Known parser limitation, explicitly asserted: `PythonParser` never emits
    `SymbolKind.CONSTANT` entries, so a module-level assignment like `MAX = 10` produces no
    extracted symbol at all -- even though it reads as a constant to a human. This is not a
    defect in `StructuralSymbolExtractor`; there is nothing for it to filter, since the data was
    never carried past `PythonParser` in the first place. Fixing it would mean changing the
    frozen `PythonParser`, which is out of scope here."""
    parse_result = PythonParser().parse(relative_path="a.py", content="MAX = 10\n")
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.symbols == ()


def test_cpp_never_extracts_constants_due_to_parser_limitation() -> None:
    """Known parser limitation, explicitly asserted: `CppParser` never emits
    `SymbolKind.CONSTANT` entries, so a real top-level `const int MAX = 10;` produces no
    extracted symbol at all. Not a defect in `StructuralSymbolExtractor` -- see the equivalent
    Python test above."""
    parse_result = CppParser().parse(relative_path="a.cpp", content="const int MAX = 10;\n")
    result = StructuralSymbolExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.symbols == ()


# --- contract identity -------------------------------------------------------------------------


def test_structural_symbol_extractor_is_a_symbol_extractor() -> None:
    """`StructuralSymbolExtractor` is a genuine `SymbolExtractor`, not just structurally similar."""
    assert isinstance(StructuralSymbolExtractor(), SymbolExtractor)
