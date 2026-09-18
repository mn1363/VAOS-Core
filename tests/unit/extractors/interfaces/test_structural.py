"""Unit tests for `src.extractors.interfaces.structural`.

Each language-specific case below parses a small, real source snippet with one of the five
existing concrete `Parser` implementations, then runs the resulting real `ParseResult` through a
single, shared `StructuralInterfaceExtractor` instance -- proving one implementation handles
every language, not five per-language variants. Every expected value in this file was obtained
by running the real parser and the real extractor together and reading off the result -- none is
hand-derived from the source snippet alone. The one exception is
`test_output_order_is_language_interface_then_trait_then_abstract_class`, which documents in its
own docstring exactly why and how it departs from this.
"""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.interfaces.base import InterfaceExtractor, InterfaceOrigin
from src.extractors.interfaces.structural import StructuralInterfaceExtractor
from src.parsers.base import FileMetadata, ParseResult
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


# --- required cases 1-3: native interface/trait symbols, one per language ------------------


def test_go_interface_symbol_is_extracted() -> None:
    """A real Go `interface`, parsed by the real `GoParser`, maps to `LANGUAGE_INTERFACE`."""
    parse_result = GoParser().parse(
        relative_path="a.go",
        content="package main\n\ntype Greeter interface {\n\tGreet() string\n}\n",
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    interface = result.interfaces[0]
    assert interface.origin == InterfaceOrigin.LANGUAGE_INTERFACE
    assert interface.name == "Greeter"
    assert interface.line_number == 3


def test_typescript_interface_symbol_is_extracted() -> None:
    """A real TypeScript `interface`, parsed by the real `TypeScriptParser`, maps to
    `LANGUAGE_INTERFACE`."""
    parse_result = TypeScriptParser().parse(
        relative_path="a.ts", content="interface Greeter {\n  greet(): string;\n}\n"
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    interface = result.interfaces[0]
    assert interface.origin == InterfaceOrigin.LANGUAGE_INTERFACE
    assert interface.name == "Greeter"
    assert interface.line_number == 1


def test_rust_trait_symbol_is_extracted() -> None:
    """A real Rust `trait`, parsed by the real `RustParser`, maps to `TRAIT`."""
    parse_result = RustParser().parse(
        relative_path="a.rs", content="trait Greeter {\n    fn greet(&self) -> String;\n}\n"
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    interface = result.interfaces[0]
    assert interface.origin == InterfaceOrigin.TRAIT
    assert interface.name == "Greeter"
    assert interface.line_number == 1


# --- required cases 4-7: the four locked Python ABC/Protocol spellings ---------------------


def test_python_class_with_bare_abc_base_is_extracted() -> None:
    """A real class with base `ABC`, parsed by the real `PythonParser`, maps to
    `ABSTRACT_CLASS`."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content="from abc import ABC\n\nclass Shape(ABC):\n    def area(self):\n        pass\n",
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    assert result.interfaces[0].origin == InterfaceOrigin.ABSTRACT_CLASS
    assert result.interfaces[0].name == "Shape"


def test_python_class_with_abc_dot_abc_base_is_extracted() -> None:
    """A real class with base `abc.ABC`, parsed by the real `PythonParser`, maps to
    `ABSTRACT_CLASS`."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content="import abc\n\nclass Shape(abc.ABC):\n    def area(self):\n        pass\n",
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    assert result.interfaces[0].origin == InterfaceOrigin.ABSTRACT_CLASS
    assert result.interfaces[0].name == "Shape"


def test_python_class_with_bare_protocol_base_is_extracted() -> None:
    """A real class with base `Protocol`, parsed by the real `PythonParser`, maps to
    `ABSTRACT_CLASS`."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content=(
            "from typing import Protocol\n\n"
            "class Shape(Protocol):\n    def area(self):\n        pass\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    assert result.interfaces[0].origin == InterfaceOrigin.ABSTRACT_CLASS
    assert result.interfaces[0].name == "Shape"


def test_python_class_with_typing_dot_protocol_base_is_extracted() -> None:
    """A real class with base `typing.Protocol`, parsed by the real `PythonParser`, maps to
    `ABSTRACT_CLASS`."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content=(
            "import typing\n\nclass Shape(typing.Protocol):\n    def area(self):\n        pass\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    assert result.interfaces[0].origin == InterfaceOrigin.ABSTRACT_CLASS
    assert result.interfaces[0].name == "Shape"


# --- required cases 8-9: the locked ABSTRACT_CLASS trigger rule ----------------------------


def test_abstractmethod_without_approved_base_is_not_extracted() -> None:
    """A real class with an `@abstractmethod`-decorated method but no approved ABC/Protocol
    base is NOT extracted -- the locked rule: the decorator alone is never sufficient."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content=(
            "from abc import abstractmethod\n\n"
            "class Shape:\n"
            "    @abstractmethod\n"
            "    def area(self):\n"
            "        pass\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.interfaces == ()


def test_approved_base_with_abstractmethod_is_extracted() -> None:
    """A real class with both an approved ABC base and an `@abstractmethod`-decorated method
    is extracted -- the base class alone was already sufficient; the decorator changes
    nothing."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content=(
            "from abc import ABC, abstractmethod\n\n"
            "class Shape(ABC):\n"
            "    @abstractmethod\n"
            "    def area(self):\n"
            "        pass\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    assert result.interfaces[0].origin == InterfaceOrigin.ABSTRACT_CLASS
    assert result.interfaces[0].name == "Shape"


# --- required case 10: an ordinary class is not extracted -----------------------------------


def test_ordinary_python_class_is_not_extracted() -> None:
    """A real, ordinary class with no base and no decorators is NOT extracted."""
    parse_result = PythonParser().parse(
        relative_path="a.py", content="class Widget:\n    def run(self):\n        pass\n"
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.interfaces == ()


# --- required case 11: method_signatures mapped exactly -------------------------------------


def test_method_signatures_are_mapped_to_bare_method_names() -> None:
    """`method_signatures` is `tuple(method.name for method in cls.methods)` -- bare declared
    names, not rendered call signatures -- for a real class with two methods."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content=(
            "from abc import ABC\n\n"
            "class Shape(ABC):\n"
            "    def area(self):\n"
            "        pass\n\n"
            "    def perimeter(self):\n"
            "        pass\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.interfaces[0].method_signatures == ("area", "perimeter")


# --- required case 12: base_interfaces copied exactly ----------------------------------------


def test_base_interfaces_is_copied_verbatim_from_base_classes() -> None:
    """`base_interfaces` is `cls.base_classes` verbatim, including a non-matching base
    alongside the approved one -- for a real class with two bases."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content=(
            "from abc import ABC\n\n"
            "class Mixin:\n    pass\n\n\n"
            "class Shape(Mixin, ABC):\n    def area(self):\n        pass\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.interfaces) == 1
    assert result.interfaces[0].name == "Shape"
    assert result.interfaces[0].base_interfaces == ("Mixin", "ABC")


# --- required case 13: native interface/trait fields use empty tuples -----------------------


def test_native_interface_and_trait_have_empty_method_signatures_and_base_interfaces() -> None:
    """A real Go `interface` and a real Rust `trait` both carry empty `method_signatures`/
    `base_interfaces` -- `ParsedSymbol` has neither field to copy from."""
    go_result = GoParser().parse(
        relative_path="a.go",
        content="package main\n\ntype Greeter interface {\n\tGreet() string\n}\n",
    )
    rust_result = RustParser().parse(
        relative_path="a.rs", content="trait Greeter {\n    fn greet(&self) -> String;\n}\n"
    )
    extractor = StructuralInterfaceExtractor()

    go_extracted = extractor.extract(go_result).interfaces[0]
    rust_extracted = extractor.extract(rust_result).interfaces[0]

    assert go_extracted.method_signatures == ()
    assert go_extracted.base_interfaces == ()
    assert rust_extracted.method_signatures == ()
    assert rust_extracted.base_interfaces == ()


# --- required case 14: fixed cross-group output order ----------------------------------------


def test_output_order_is_language_interface_then_trait_then_abstract_class() -> None:
    """The fixed group order -- `LANGUAGE_INTERFACE`, then `TRAIT`, then `ABSTRACT_CLASS` --
    holds when all three occur together.

    No single real source file can exercise all three `InterfaceOrigin` values at once: each is
    exclusive to a different language/construct (`SymbolKind.INTERFACE` only from Go/TypeScript,
    `SymbolKind.TRAIT` only from Rust, an approved ABC/Protocol base only realistically from
    Python). So, uniquely among the tests in this file, this one combines three genuinely real,
    independently-parsed fragments -- a real Go `interface`, a real Rust `trait`, and a real
    Python `ABC` class, each produced by its own real `Parser` exactly as in the tests above --
    into one synthetic `ParseResult`, purely to exercise `StructuralInterfaceExtractor`'s own
    cross-language group-ordering logic, which no single `Parser` can be used to exercise on its
    own. Every `ParsedSymbol`/`ParsedClass` combined below is genuine, unmodified real parser
    output; only their combination into a single `ParseResult` is synthetic."""
    go_result = GoParser().parse(
        relative_path="a.go",
        content="package main\n\ntype Reader interface {\n\tRead() string\n}\n",
    )
    rust_result = RustParser().parse(
        relative_path="a.rs", content="trait Writer {\n    fn write(&self, s: String);\n}\n"
    )
    python_result = PythonParser().parse(
        relative_path="a.py", content="from abc import ABC\n\nclass Shape(ABC):\n    pass\n"
    )
    combined = ParseResult.ok(
        relative_path="combined",
        language=SourceLanguage.UNKNOWN,
        metadata=FileMetadata(
            relative_path="combined",
            language=SourceLanguage.UNKNOWN,
            size_bytes=0,
            line_count=0,
            content_hash="",
        ),
        classes=python_result.classes,
        symbols=go_result.symbols + rust_result.symbols,
    )

    result = StructuralInterfaceExtractor().extract(combined)

    assert result.succeeded is True
    assert [(i.origin, i.name) for i in result.interfaces] == [
        (InterfaceOrigin.LANGUAGE_INTERFACE, "Reader"),
        (InterfaceOrigin.TRAIT, "Writer"),
        (InterfaceOrigin.ABSTRACT_CLASS, "Shape"),
    ]


# --- required case 15: source order preserved within each group ------------------------------


def test_source_order_preserved_among_multiple_go_interfaces() -> None:
    """Two real Go interfaces are extracted in source order."""
    parse_result = GoParser().parse(
        relative_path="a.go",
        content=(
            "package main\n\n"
            "type Reader interface {\n\tRead() string\n}\n\n"
            "type Writer interface {\n\tWrite(s string)\n}\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert [(i.name, i.line_number) for i in result.interfaces] == [
        ("Reader", 3),
        ("Writer", 7),
    ]


def test_source_order_preserved_among_multiple_rust_traits() -> None:
    """Two real Rust traits are extracted in source order."""
    parse_result = RustParser().parse(
        relative_path="a.rs",
        content=(
            "trait Reader {\n    fn read(&self) -> String;\n}\n\n"
            "trait Writer {\n    fn write(&self, s: String);\n}\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert [(i.name, i.line_number) for i in result.interfaces] == [
        ("Reader", 1),
        ("Writer", 5),
    ]


def test_source_order_preserved_among_multiple_python_abc_classes() -> None:
    """Two real Python ABC classes are extracted in source order."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content="from abc import ABC\n\nclass First(ABC):\n    pass\n\n\nclass Second(ABC):\n    pass\n",
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert [(i.name, i.line_number) for i in result.interfaces] == [
        ("First", 3),
        ("Second", 7),
    ]


# --- required case 16: empty ParseResult -------------------------------------------------------


def test_empty_parse_result_produces_empty_interfaces() -> None:
    """A file with no interface-shaped declarations produces a successful, empty result."""
    parse_result = PythonParser().parse(relative_path="empty.py", content="")
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.interfaces == ()


# --- required case 17: failed ParseResult / ValidationError -----------------------------------


def test_failed_parse_result_raises_validation_error() -> None:
    """A failed `ParseResult` raises `ValidationError` via `require_successful_parse`,
    unchanged."""
    with pytest.raises(ValidationError):
        StructuralInterfaceExtractor().extract(_failed_parse_result())


# --- required case 18: duplicate entries preserved ---------------------------------------------


def test_duplicate_class_names_produce_two_entries() -> None:
    """The same class name, declared twice with the same approved base, produces two entries
    -- not merged, not deduplicated."""
    parse_result = PythonParser().parse(
        relative_path="a.py",
        content=(
            "from abc import ABC\n\nclass Shape(ABC):\n    pass\n\n\nclass Shape(ABC):\n    pass\n"
        ),
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert len(result.interfaces) == 2
    assert [i.name for i in result.interfaces] == ["Shape", "Shape"]
    assert [i.line_number for i in result.interfaces] == [3, 7]


# --- required case 19: contract identity -------------------------------------------------------


def test_structural_interface_extractor_is_an_interface_extractor() -> None:
    """`StructuralInterfaceExtractor` is a genuine `InterfaceExtractor`, not just structurally
    similar."""
    assert isinstance(StructuralInterfaceExtractor(), InterfaceExtractor)


# --- required case 20: C++ pure-virtual limitation, explicitly asserted ------------------------


def test_cpp_pure_virtual_class_is_not_extracted_due_to_parser_limitation() -> None:
    """Known parser limitation, explicitly asserted: a real C++ class composed entirely of
    pure-virtual methods (`= 0`) is NOT extracted as `ABSTRACT_CLASS`. `CppParser` discards the
    `virtual` keyword itself as prefix noise when building a method's parsed record and never
    captures a `= 0` pure-virtual marker anywhere, so `ParsedClass.base_classes` is empty and
    `ParsedFunction` carries no field this extractor -- or any extractor limited to
    `parsers.base` DTOs -- could recognize the class by. Not a defect in
    `StructuralInterfaceExtractor`; there is nothing for it to recognize, since the data was
    never carried past `CppParser` in the first place. Fixing it would mean changing the frozen
    `CppParser`, which is out of scope here."""
    parse_result = CppParser().parse(
        relative_path="a.cpp",
        content="class Shape {\npublic:\n    virtual double area() = 0;\n};\n",
    )
    result = StructuralInterfaceExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.interfaces == ()


# --- one implementation, five languages ---------------------------------------------------------


def test_single_extractor_instance_handles_all_five_languages() -> None:
    """One `StructuralInterfaceExtractor` instance, reused, succeeds against real `ParseResult`s
    from all five parsers -- returning empty interfaces where none of the three recognized forms
    is present, and not raising for any of them."""
    extractor = StructuralInterfaceExtractor()
    cases: tuple[ParseResult, ...] = (
        PythonParser().parse(relative_path="a.py", content="class Widget:\n    pass\n"),
        RustParser().parse(relative_path="a.rs", content="struct Widget;\n"),
        GoParser().parse(relative_path="a.go", content="package main\n"),
        TypeScriptParser().parse(relative_path="a.ts", content="class Widget {}\n"),
        CppParser().parse(relative_path="a.cpp", content="class Widget {};\n"),
    )
    for parse_result in cases:
        result = extractor.extract(parse_result)
        assert result.succeeded is True
        assert result.interfaces == ()
