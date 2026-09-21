"""Unit tests for `src.extractors.foundation.structural`.

Each language-specific case below parses a small, real source snippet with one of the five
existing concrete `Parser` implementations, then runs the resulting real `ParseResult` through a
`StructuralFoundationExtractor` -- proving one implementation handles every language, not five
per-language variants. Every expected value in this file was obtained by running the real parser
and the real extractor together and reading off the result -- none is hand-derived from the
source snippet alone. Where a test documents a parser-layer limitation (Go carries no docstring,
ordinary C++ carries no exports, and so on), it asserts the parser's own output first, so the
limitation is proven to live in `ParseResult` and not in the extractor.
"""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.foundation.base import (
    FoundationCandidate,
    FoundationCandidateKind,
    FoundationExtractionResult,
    FoundationExtractor,
)
from src.extractors.foundation.structural import StructuralFoundationExtractor
from src.parsers.base import ParseResult, SymbolKind
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


def _cls(
    name: str, relative_path: str, line_number: int, *, public: bool, documented: bool
) -> FoundationCandidate:
    """Build the exact `CLASS` candidate the locked mapping is expected to produce."""
    return FoundationCandidate(
        name=name,
        kind=FoundationCandidateKind.CLASS,
        relative_path=relative_path,
        is_public=public,
        has_docstring=documented,
        signals=(),
        line_number=line_number,
    )


def _fn(
    name: str, relative_path: str, line_number: int, *, public: bool, documented: bool
) -> FoundationCandidate:
    """Build the exact `FUNCTION` candidate the locked mapping is expected to produce."""
    return FoundationCandidate(
        name=name,
        kind=FoundationCandidateKind.FUNCTION,
        relative_path=relative_path,
        is_public=public,
        has_docstring=documented,
        signals=(),
        line_number=line_number,
    )


def _extract_python(content: str, relative_path: str = "a.py") -> FoundationExtractionResult:
    """Parse `content` with the real `PythonParser` and run the real extractor over it."""
    return StructuralFoundationExtractor().extract(
        PythonParser().parse(relative_path=relative_path, content=content)
    )


# --- required cases 1-2: class and function extraction ----------------------------------------


def test_class_is_extracted() -> None:
    """A real Python class maps to one `CLASS` candidate, with name, path, and line copied."""
    result = _extract_python("class Widget:\n    pass\n", relative_path="pkg/widget.py")

    assert result.succeeded is True
    assert result.error_message is None
    assert result.relative_path == "pkg/widget.py"
    assert result.candidates == (
        _cls("Widget", "pkg/widget.py", 1, public=False, documented=False),
    )


def test_function_is_extracted() -> None:
    """A real Python top-level function maps to one `FUNCTION` candidate."""
    result = _extract_python("def build():\n    pass\n", relative_path="pkg/build.py")

    assert result.succeeded is True
    assert result.candidates == (_fn("build", "pkg/build.py", 1, public=False, documented=False),)


# --- required cases 3-7: has_docstring is exactly `docstring is not None` ------------------------


def test_documented_class_has_docstring() -> None:
    """A real class with a docstring produces `has_docstring=True`."""
    result = _extract_python('class Widget:\n    """A widget."""\n')

    assert result.candidates == (_cls("Widget", "a.py", 1, public=False, documented=True),)


def test_undocumented_class_has_no_docstring() -> None:
    """A real class without a docstring produces `has_docstring=False`."""
    result = _extract_python("class Widget:\n    x = 1\n")

    assert result.candidates == (_cls("Widget", "a.py", 1, public=False, documented=False),)


def test_documented_function_has_docstring() -> None:
    """A real function with a docstring produces `has_docstring=True`."""
    result = _extract_python('def build():\n    """Build one."""\n')

    assert result.candidates == (_fn("build", "a.py", 1, public=False, documented=True),)


def test_undocumented_function_has_no_docstring() -> None:
    """A real function without a docstring produces `has_docstring=False`."""
    result = _extract_python("def build():\n    return 1\n")

    assert result.candidates == (_fn("build", "a.py", 1, public=False, documented=False),)


def test_empty_string_docstring_still_counts_as_documented() -> None:
    """`has_docstring` is `docstring is not None`, never truthiness: a class, a whitespace-only
    class docstring, and a function whose docstring is the empty string are all documented.
    The parser's own output is asserted first, proving each docstring really is the empty
    string."""
    content = 'class Blank:\n    """"""\n\n\nclass Spaces:\n    """   """\n\n\ndef blank_fn():\n    """"""\n'
    parse_result = PythonParser().parse(relative_path="e.py", content=content)
    assert [cls.docstring for cls in parse_result.classes] == ["", ""]
    assert [function.docstring for function in parse_result.functions] == [""]

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == (
        _cls("Blank", "e.py", 1, public=False, documented=True),
        _cls("Spaces", "e.py", 5, public=False, documented=True),
        _fn("blank_fn", "e.py", 9, public=False, documented=True),
    )


# --- required cases 8-10: is_public is export-list membership by `ParsedExport.name` ------------


def test_exported_names_are_public() -> None:
    """A class and a function named in `__all__` produce `is_public=True`."""
    result = _extract_python(
        '__all__ = ["Widget", "build"]\n\n\nclass Widget:\n    pass\n\n\ndef build():\n    pass\n'
    )

    assert result.candidates == (
        _cls("Widget", "a.py", 4, public=True, documented=False),
        _fn("build", "a.py", 8, public=True, documented=False),
    )


def test_non_exported_names_are_not_public() -> None:
    """A class and a function absent from `__all__` produce `is_public=False`, even though
    other names in the same file are exported."""
    result = _extract_python(
        '__all__ = ["Widget"]\n\n\nclass Widget:\n    pass\n\n\nclass Other:\n    pass\n\n\n'
        "def helper():\n    pass\n"
    )

    assert result.candidates == (
        _cls("Widget", "a.py", 4, public=True, documented=False),
        _cls("Other", "a.py", 8, public=False, documented=False),
        _fn("helper", "a.py", 12, public=False, documented=False),
    )


def test_is_public_compares_against_export_name_not_the_export_object() -> None:
    """`parse_result.exports` holds `ParsedExport` objects, not strings. Comparing a string
    directly against them is always False, so `is_public` must compare against `export.name`.
    This test proves both halves: the direct comparison is False for a name that really is
    exported, while the extractor still reports it as public."""
    parse_result = PythonParser().parse(
        relative_path="a.py", content='__all__ = ["Widget"]\n\n\nclass Widget:\n    pass\n'
    )
    assert [export.name for export in parse_result.exports] == ["Widget"]
    assert "Widget" not in parse_result.exports

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == (_cls("Widget", "a.py", 4, public=True, documented=False),)


def test_exported_name_without_a_class_or_function_produces_no_candidate() -> None:
    """Exports only decide `is_public`; they never create candidates. A Go `interface` is
    exported (capitalized) but is a symbol, not a `ParsedClass`, so it yields nothing."""
    parse_result = GoParser().parse(
        relative_path="a.go",
        content="package main\n\ntype Greeter interface {\n\tGreet() string\n}\n",
    )
    assert [export.name for export in parse_result.exports] == ["Greeter"]

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == ()


# --- required case 11: signals are always () ------------------------------------------------


def test_signals_are_always_empty() -> None:
    """`signals` is `()` for every candidate, even where the parser carries inputs a signal
    could have been derived from (a decorator and a base class). The parser's own output is
    asserted first, proving those inputs really exist and are deliberately ignored."""
    content = (
        "from dataclasses import dataclass\n\n\nclass Base:\n    pass\n\n\n@dataclass\n"
        "class Point(Base):\n    x: int = 0\n\n\n@staticmethod\ndef deco():\n    pass\n"
    )
    parse_result = PythonParser().parse(relative_path="p.py", content=content)
    point = next(cls for cls in parse_result.classes if cls.name == "Point")
    assert point.decorators == ("dataclass",)
    assert point.base_classes == ("Base",)

    result = StructuralFoundationExtractor().extract(parse_result)

    assert [candidate.name for candidate in result.candidates] == ["Base", "Point", "deco"]
    assert all(candidate.signals == () for candidate in result.candidates)


# --- required cases 12-14: duplicates are preserved exactly as parsed -------------------------


def test_duplicate_classes_produce_two_candidates() -> None:
    """The same class name declared twice produces two candidates -- not merged, not
    deduplicated, and the second's docstring is not merged into the first."""
    result = _extract_python('class Shape:\n    pass\n\n\nclass Shape:\n    """Second."""\n')

    assert result.candidates == (
        _cls("Shape", "a.py", 1, public=False, documented=False),
        _cls("Shape", "a.py", 5, public=False, documented=True),
    )


def test_duplicate_functions_produce_two_candidates() -> None:
    """The same function name declared twice (an overload, a redefinition) produces two
    candidates, each keeping its own line and its own `has_docstring`."""
    result = _extract_python('def f():\n    pass\n\n\ndef f():\n    """Second."""\n')

    assert result.candidates == (
        _fn("f", "a.py", 1, public=False, documented=False),
        _fn("f", "a.py", 5, public=False, documented=True),
    )


def test_class_and_function_with_the_same_name_are_both_emitted() -> None:
    """A class and a free function sharing one name in one file produce two candidates that
    differ only by kind and line -- identity is never altered to tell them apart."""
    result = _extract_python("class X:\n    pass\n\n\ndef X():\n    pass\n")

    assert result.candidates == (
        _cls("X", "a.py", 1, public=False, documented=False),
        _fn("X", "a.py", 5, public=False, documented=False),
    )
    assert result.candidates[0].name == result.candidates[1].name
    assert result.candidates[0].relative_path == result.candidates[1].relative_path


# --- required cases 15-16: source order is preserved, never sorted ------------------------------


def test_class_source_order_is_preserved() -> None:
    """Classes come out in `parse_result.classes` order -- source order, not alphabetical."""
    result = _extract_python(
        "class Zeta:\n    pass\n\n\nclass Alpha:\n    pass\n\n\nclass Mid:\n    pass\n"
    )

    assert [candidate.name for candidate in result.candidates] == ["Zeta", "Alpha", "Mid"]


def test_function_source_order_is_preserved() -> None:
    """Functions come out in `parse_result.functions` order -- source order, not alphabetical."""
    result = _extract_python(
        "def zulu():\n    pass\n\n\ndef alpha():\n    pass\n\n\ndef mike():\n    pass\n"
    )

    assert [candidate.name for candidate in result.candidates] == ["zulu", "alpha", "mike"]


def test_all_classes_precede_all_functions_and_nothing_is_sorted_by_line() -> None:
    """Output is every class, then every function -- even when a function is declared on an
    earlier line than a class. Sorting by line number would put `early` first; it does not."""
    result = _extract_python("def early():\n    pass\n\n\nclass Late:\n    pass\n")

    assert result.candidates == (
        _cls("Late", "a.py", 5, public=False, documented=False),
        _fn("early", "a.py", 1, public=False, documented=False),
    )


# --- required case 17: methods are never emitted ------------------------------------------------


def test_methods_are_not_emitted() -> None:
    """A class's methods produce no candidates of their own -- only the class does. The
    parser's own output is asserted first, proving the methods really were parsed."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content=(
            "class Widget:\n    def show(self):\n        pass\n\n    def hide(self):\n"
            "        pass\n\n\ndef build():\n    pass\n"
        ),
    )
    assert [method.name for method in parse_result.classes[0].methods] == ["show", "hide"]

    result = StructuralFoundationExtractor().extract(parse_result)

    assert [(c.name, c.kind) for c in result.candidates] == [
        ("Widget", FoundationCandidateKind.CLASS),
        ("build", FoundationCandidateKind.FUNCTION),
    ]


# --- required case 18: native interfaces/traits are not candidates ------------------------------


def test_go_interface_is_not_a_candidate() -> None:
    """A real Go `interface` is a symbol, not a `ParsedClass`, so it is not a candidate."""
    parse_result = GoParser().parse(
        relative_path="a.go",
        content="package main\n\ntype Greeter interface {\n\tGreet() string\n}\n",
    )
    interfaces = [s.name for s in parse_result.symbols if s.kind == SymbolKind.INTERFACE]
    assert interfaces == ["Greeter"]
    assert parse_result.classes == ()

    assert StructuralFoundationExtractor().extract(parse_result).candidates == ()


def test_typescript_interface_is_not_a_candidate() -> None:
    """A real TypeScript `interface` is a symbol, not a `ParsedClass`, so it is not a
    candidate."""
    parse_result = TypeScriptParser().parse(
        relative_path="a.ts", content="interface Greeter {\n  greet(): string;\n}\n"
    )
    interfaces = [s.name for s in parse_result.symbols if s.kind == SymbolKind.INTERFACE]
    assert interfaces == ["Greeter"]
    assert parse_result.classes == ()

    assert StructuralFoundationExtractor().extract(parse_result).candidates == ()


def test_rust_trait_is_not_a_candidate() -> None:
    """A real Rust `trait` is a symbol, not a `ParsedClass`, so it is not a candidate."""
    parse_result = RustParser().parse(
        relative_path="a.rs", content="trait Greeter {\n    fn greet(&self) -> String;\n}\n"
    )
    traits = [s.name for s in parse_result.symbols if s.kind == SymbolKind.TRAIT]
    assert traits == ["Greeter"]
    assert parse_result.classes == ()

    assert StructuralFoundationExtractor().extract(parse_result).candidates == ()


# --- required cases 19-20: empty and failed ParseResult ----------------------------------------


def test_empty_parse_result_produces_empty_candidates() -> None:
    """A file with no classes or functions produces a successful, empty result."""
    result = _extract_python("", relative_path="empty.py")

    assert result.succeeded is True
    assert result.error_message is None
    assert result.relative_path == "empty.py"
    assert result.candidates == ()


def test_failed_parse_result_raises_validation_error() -> None:
    """A failed `ParseResult` raises `ValidationError` via `require_successful_parse`,
    unchanged -- it is never converted into a failed `FoundationExtractionResult`."""
    with pytest.raises(ValidationError):
        StructuralFoundationExtractor().extract(_failed_parse_result())


# --- required case 21: contract identity --------------------------------------------------------


def test_structural_foundation_extractor_is_a_foundation_extractor() -> None:
    """`StructuralFoundationExtractor` is a genuine `FoundationExtractor`, not just
    structurally similar."""
    assert isinstance(StructuralFoundationExtractor(), FoundationExtractor)


def test_extractor_is_zero_argument_and_stateless() -> None:
    """No `__init__` override exists, and one instance gives the same answer no matter what
    it processed before -- it holds no state between calls."""
    assert "__init__" not in vars(StructuralFoundationExtractor)

    extractor = StructuralFoundationExtractor()
    first = PythonParser().parse(relative_path="a.py", content="class A:\n    pass\n")
    second = PythonParser().parse(relative_path="b.py", content="def b():\n    pass\n")
    before = extractor.extract(first)
    extractor.extract(second)

    assert extractor.extract(first) == before


# --- required case 22: Go carries no docstring data ---------------------------------------------


def test_go_docstring_limitation() -> None:
    """Known parser limitation, explicitly asserted: `GoParser` never sets `docstring`, so
    every Go candidate has `has_docstring=False` even when a `//` doc comment sits directly
    above it. The parser's own output is asserted first. Exported Go names are still exact
    export-list members, so `is_public` is True for them."""
    parse_result = GoParser().parse(
        relative_path="a.go",
        content=(
            "package main\n\n// Widget is exported and documented.\ntype Widget struct{}\n\n"
            "type hidden struct{}\n\nfunc (w *Widget) Show() {}\n\n"
            "// Build is exported and documented.\nfunc Build() {}\n\nfunc helper() {}\n"
        ),
    )
    assert all(cls.docstring is None for cls in parse_result.classes)
    assert all(function.docstring is None for function in parse_result.functions)

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == (
        _cls("Widget", "a.go", 4, public=True, documented=False),
        _cls("hidden", "a.go", 6, public=False, documented=False),
        _fn("Build", "a.go", 11, public=True, documented=False),
        _fn("helper", "a.go", 13, public=False, documented=False),
    )


# --- required case 23: ordinary C++ carries no export data ----------------------------------------


def test_cpp_export_limitation() -> None:
    """Known parser limitation, explicitly asserted: ordinary (non-module) C++ has no export
    concept, so `CppParser` produces no `ParsedExport` entries and every candidate has
    `is_public=False` -- without proving anything about the C++ constructs' real visibility.
    Only C++20 `export`-prefixed declarations become exports (and therefore public)."""
    ordinary = CppParser().parse(
        relative_path="a.cpp",
        content="/// A widget.\nclass Widget {\npublic:\n    void show();\n};\n\n"
        "/// Build one.\nint build() { return 1; }\n",
    )
    assert ordinary.exports == ()

    ordinary_result = StructuralFoundationExtractor().extract(ordinary)

    assert ordinary_result.candidates == (
        _cls("Widget", "a.cpp", 2, public=False, documented=True),
        _fn("build", "a.cpp", 8, public=False, documented=True),
    )

    module = CppParser().parse(
        relative_path="a.cppm",
        content="export class Widget {\n};\n\nexport int build() { return 1; }\n\n"
        "int helper() { return 2; }\n",
    )
    assert [export.name for export in module.exports] == ["Widget", "build"]

    module_result = StructuralFoundationExtractor().extract(module)

    assert module_result.candidates == (
        _cls("Widget", "a.cppm", 1, public=True, documented=False),
        _fn("build", "a.cppm", 4, public=True, documented=False),
        _fn("helper", "a.cppm", 6, public=False, documented=False),
    )


# --- required case 24: one real parser case per language ---------------------------------------


def test_python_real_parser_case() -> None:
    """A real Python file: exported/documented and private/undocumented classes and
    functions, with a method that must not be emitted."""
    content = (
        '"""Module."""\n__all__ = ["Widget", "build"]\n\n\nclass Widget:\n    """A widget."""\n\n'
        "    def show(self):\n        pass\n\n\nclass _Internal:\n    pass\n\n\n"
        'def build():\n    """Build one."""\n\n\ndef _helper():\n    pass\n'
    )
    result = _extract_python(content, relative_path="a.py")

    assert result.candidates == (
        _cls("Widget", "a.py", 5, public=True, documented=True),
        _cls("_Internal", "a.py", 12, public=False, documented=False),
        _fn("build", "a.py", 16, public=True, documented=True),
        _fn("_helper", "a.py", 20, public=False, documented=False),
    )


def test_go_real_parser_case() -> None:
    """A real Go file: capitalized names are export-list members, so they are public; the
    receiver method `Show` is not emitted."""
    result = StructuralFoundationExtractor().extract(
        GoParser().parse(
            relative_path="a.go",
            content=(
                "package main\n\n// Widget is exported and documented.\ntype Widget struct{}\n\n"
                "type hidden struct{}\n\nfunc (w *Widget) Show() {}\n\n"
                "// Build is exported and documented.\nfunc Build() {}\n\nfunc helper() {}\n"
            ),
        )
    )

    assert result.candidates == (
        _cls("Widget", "a.go", 4, public=True, documented=False),
        _cls("hidden", "a.go", 6, public=False, documented=False),
        _fn("Build", "a.go", 11, public=True, documented=False),
        _fn("helper", "a.go", 13, public=False, documented=False),
    )


def test_rust_real_parser_case() -> None:
    """A real Rust file: `pub` items are export-list members; the `impl` method `show` is
    not emitted."""
    result = StructuralFoundationExtractor().extract(
        RustParser().parse(
            relative_path="a.rs",
            content=(
                "/// A widget.\npub struct Widget;\n\nstruct Internal;\n\nimpl Widget {\n"
                "    pub fn show(&self) {}\n}\n\n/// Build one.\npub fn build() {}\n\nfn helper() {}\n"
            ),
        )
    )

    assert result.candidates == (
        _cls("Widget", "a.rs", 2, public=True, documented=True),
        _cls("Internal", "a.rs", 4, public=False, documented=False),
        _fn("build", "a.rs", 11, public=True, documented=True),
        _fn("helper", "a.rs", 13, public=False, documented=False),
    )


def test_typescript_real_parser_case() -> None:
    """A real TypeScript file: `export`-prefixed declarations are public; the class method
    `show` is not emitted."""
    result = StructuralFoundationExtractor().extract(
        TypeScriptParser().parse(
            relative_path="a.ts",
            content=(
                "/** A widget. */\nexport class Widget {\n  show(): void {}\n}\n\nclass Internal {}\n\n"
                "/** Build one. */\nexport function build(): void {}\n\nfunction helper(): void {}\n"
            ),
        )
    )

    assert result.candidates == (
        _cls("Widget", "a.ts", 2, public=True, documented=True),
        _cls("Internal", "a.ts", 6, public=False, documented=False),
        _fn("build", "a.ts", 9, public=True, documented=True),
        _fn("helper", "a.ts", 11, public=False, documented=False),
    )


def test_cpp_real_parser_case() -> None:
    """A real (ordinary) C++ file: documented class and free function, neither public since
    ordinary C++ has no exports; the class method `show` is not emitted."""
    result = StructuralFoundationExtractor().extract(
        CppParser().parse(
            relative_path="a.cpp",
            content=(
                "/// A widget.\nclass Widget {\npublic:\n    void show();\n};\n\n"
                "/// Build one.\nint build() { return 1; }\n"
            ),
        )
    )

    assert result.candidates == (
        _cls("Widget", "a.cpp", 2, public=False, documented=True),
        _fn("build", "a.cpp", 8, public=False, documented=True),
    )


def test_single_extractor_instance_handles_all_five_languages() -> None:
    """One `StructuralFoundationExtractor` instance, reused, succeeds against real
    `ParseResult`s from all five parsers and emits exactly one class candidate for each."""
    extractor = StructuralFoundationExtractor()
    cases: tuple[ParseResult, ...] = (
        PythonParser().parse(relative_path="a.py", content="class Widget:\n    pass\n"),
        RustParser().parse(relative_path="a.rs", content="struct Widget;\n"),
        GoParser().parse(relative_path="a.go", content="package main\n\ntype Widget struct{}\n"),
        TypeScriptParser().parse(relative_path="a.ts", content="class Widget {}\n"),
        CppParser().parse(relative_path="a.cpp", content="class Widget {};\n"),
    )
    for parse_result in cases:
        result = extractor.extract(parse_result)
        assert result.succeeded is True
        assert [(c.name, c.kind) for c in result.candidates] == [
            ("Widget", FoundationCandidateKind.CLASS)
        ]
        assert result.candidates[0].signals == ()


# --- documented parser-level limitations that pass through unchanged -----------------------------


def test_python_file_without_all_has_no_public_candidates() -> None:
    """Known parser limitation, explicitly asserted: a Python file with no `__all__` has no
    exports, so every candidate is `is_public=False` -- which means "not in the parser's
    export list", not "private"."""
    parse_result = PythonParser().parse(
        relative_path="a.py", content="class Widget:\n    pass\n\n\ndef build():\n    pass\n"
    )
    assert parse_result.exports == ()

    result = StructuralFoundationExtractor().extract(parse_result)

    assert [c.is_public for c in result.candidates] == [False, False]


def test_python_all_augmented_assignment_is_not_captured() -> None:
    """Known parser limitation, explicitly asserted: `PythonParser` reads only the literal
    `__all__ = [...]` assignment, so a name added later by `__all__ += [...]` is not an
    export and its candidate is `is_public=False`."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content='__all__ = ["a"]\n__all__ += ["b"]\n\n\ndef a():\n    pass\n\n\ndef b():\n    pass\n',
    )
    assert [export.name for export in parse_result.exports] == ["a"]

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == (
        _fn("a", "a.py", 5, public=True, documented=False),
        _fn("b", "a.py", 9, public=False, documented=False),
    )


def test_typescript_renamed_export_is_reported_under_the_alias() -> None:
    """Known parser limitation, explicitly asserted: `export { B as Renamed }` puts the alias
    `Renamed` in the export list, not the declared name `B`, so the class `B` is
    `is_public=False` even though it is exported under another name."""
    parse_result = TypeScriptParser().parse(
        relative_path="a.ts", content="class B {}\n\nexport { B as Renamed };\n"
    )
    assert [export.name for export in parse_result.exports] == ["Renamed"]

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == (_cls("B", "a.ts", 1, public=False, documented=False),)


def test_rust_restricted_visibility_counts_as_exported() -> None:
    """Known parser limitation, explicitly asserted: `RustParser` treats any declaration whose
    line starts with `pub` as exported, including `pub(crate)`, so that function is
    `is_public=True` while a plain private function is not."""
    parse_result = RustParser().parse(
        relative_path="a.rs", content="pub(crate) fn crate_fn() {}\n\nfn private_fn() {}\n"
    )
    assert [export.name for export in parse_result.exports] == ["crate_fn"]

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == (
        _fn("crate_fn", "a.rs", 1, public=True, documented=False),
        _fn("private_fn", "a.rs", 3, public=False, documented=False),
    )


def test_rust_doc_comment_separated_by_an_attribute_is_not_attached() -> None:
    """Known parser limitation, explicitly asserted: `RustParser` attaches only `///` lines
    directly above a declaration, so a doc comment separated from it by a `#[derive]` line
    yields no docstring and `has_docstring=False`."""
    parse_result = RustParser().parse(
        relative_path="a.rs",
        content="/// Documented, but above an attribute.\n#[derive(Debug)]\npub struct Point;\n",
    )
    assert parse_result.classes[0].docstring is None

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == (_cls("Point", "a.rs", 3, public=True, documented=False),)


def test_typescript_plain_block_comment_can_inherit_an_earlier_jsdoc() -> None:
    """Known parser limitation, explicitly asserted: when the line above a TypeScript
    declaration ends a plain `/* ... */` comment and an unrelated `/** ... */` block exists
    earlier in the file, `TypeScriptParser` attaches the earlier block, so the undocumented
    function `g` reports `has_docstring=True`. The extractor copies the parser's answer."""
    parse_result = TypeScriptParser().parse(
        relative_path="a.ts",
        content="/** real doc */\nclass K {}\n\n/* plain */\nfunction g() {}\n",
    )
    assert parse_result.functions[0].docstring is not None

    result = StructuralFoundationExtractor().extract(parse_result)

    assert result.candidates == (
        _cls("K", "a.ts", 2, public=False, documented=True),
        _fn("g", "a.ts", 5, public=False, documented=True),
    )
