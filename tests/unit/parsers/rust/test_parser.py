"""Unit tests for `src.parsers.rust.parser`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.parsers.base import SymbolKind
from src.parsers.rust.parser import RustParser


def test_language_is_rust() -> None:
    """`RustParser.language` should report `SourceLanguage.RUST`."""
    assert RustParser().language is SourceLanguage.RUST


@pytest.mark.parametrize("path", ["main.rs", "src/lib.rs", "Main.RS"])
def test_supports_accepts_rust_extension(path: str) -> None:
    """`supports` should accept `.rs` files, case-insensitively."""
    assert RustParser().supports(path) is True


@pytest.mark.parametrize("path", ["main.txt", "main.go"])
def test_supports_rejects_non_rust_extensions(path: str) -> None:
    """`supports` should reject files without the Rust extension."""
    assert RustParser().supports(path) is False


def test_parse_rejects_a_blank_relative_path() -> None:
    """`parse` should raise `ValidationError` for a blank `relative_path`."""
    with pytest.raises(ValidationError):
        RustParser().parse(relative_path="", content="fn main() {}")


def test_parse_succeeds_on_empty_content() -> None:
    """`parse` should succeed on an empty file."""
    result = RustParser().parse(relative_path="empty.rs", content="")
    assert result.succeeded is True
    assert result.metadata is not None


def test_parse_extracts_a_mod_declaration() -> None:
    """`parse` should extract a `mod name;` declaration as a `ParsedModule`."""
    result = RustParser().parse(relative_path="lib.rs", content="pub mod widgets;\n")
    assert [module.name for module in result.modules] == ["widgets"]


def test_parse_extracts_a_simple_use_statement() -> None:
    """`parse` should extract a plain `use a::b::C;` statement."""
    result = RustParser().parse(relative_path="lib.rs", content="use std::collections::HashMap;\n")

    assert len(result.imports) == 1
    imported = result.imports[0]
    assert imported.module == "std::collections"
    assert imported.imported_names == ("HashMap",)


def test_parse_extracts_a_grouped_use_statement() -> None:
    """`parse` should extract every entry in a brace-grouped `use std::{a, b};` statement."""
    result = RustParser().parse(relative_path="lib.rs", content="use std::{fmt, io::Read};\n")

    modules = {(imported.module, imported.imported_names) for imported in result.imports}
    assert ("std", ("fmt",)) in modules
    assert ("std", ("io::Read",)) in modules


def test_parse_extracts_use_alias() -> None:
    """`parse` should extract the alias from a `use a::B as C;` statement."""
    result = RustParser().parse(
        relative_path="lib.rs", content="use crate::widgets::Widget as W;\n"
    )

    imported = result.imports[0]
    assert imported.alias == "W"
    assert imported.is_relative is True


def test_parse_marks_crate_self_super_paths_as_relative() -> None:
    """`parse` should mark `crate::`/`self::`/`super::`-rooted `use` paths as relative."""
    result = RustParser().parse(relative_path="lib.rs", content="use super::helpers::*;\n")

    imported = result.imports[0]
    assert imported.is_relative is True
    assert imported.imported_names == ("*",)


def test_parse_extracts_a_struct_with_docstring() -> None:
    """`parse` should extract a struct's name and its leading `///` doc comment."""
    content = "/// A point in space.\npub struct Point {\n    pub x: f64,\n}\n"
    result = RustParser().parse(relative_path="lib.rs", content=content)

    assert len(result.classes) == 1
    point = result.classes[0]
    assert point.name == "Point"
    assert point.docstring == "A point in space."


def test_parse_attaches_inherent_impl_methods_to_their_struct() -> None:
    """`parse` should attach a `impl Point { fn ... }` method to the `Point` class."""
    content = (
        "pub struct Point {\n    x: f64,\n}\n\n"
        "impl Point {\n"
        "    pub fn new(x: f64) -> Self {\n        Point { x }\n    }\n"
        "}\n"
    )
    result = RustParser().parse(relative_path="lib.rs", content=content)

    point = result.classes[0]
    assert [method.name for method in point.methods] == ["new"]
    assert point.methods[0].is_method is True


def test_parse_records_trait_impl_as_a_base_class() -> None:
    """`parse` should record the trait in `impl Trait for Type` as a base class."""
    content = (
        "pub struct Point {\n    x: f64,\n}\n\n"
        "pub trait Shape {\n    fn area(&self) -> f64;\n}\n\n"
        "impl Shape for Point {\n"
        "    fn area(&self) -> f64 {\n        0.0\n    }\n"
        "}\n"
    )
    result = RustParser().parse(relative_path="lib.rs", content=content)

    point = result.classes[0]
    assert point.base_classes == ("Shape",)
    assert [method.name for method in point.methods] == ["area"]


def test_parse_treats_a_signature_only_trait_method_as_a_method_not_a_function() -> None:
    """`parse` should classify a body-less trait method signature as a method, not a function."""
    content = "pub trait Shape {\n    fn area(&self) -> f64;\n}\n"
    result = RustParser().parse(relative_path="lib.rs", content=content)

    assert result.functions == ()
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [symbol.name for symbol in methods] == ["area"]


def test_parse_extracts_a_free_function_with_parameters_and_return_type() -> None:
    """`parse` should extract a free function's parameters and `-> ReturnType`."""
    content = "pub fn add(x: i32, y: i32) -> i32 {\n    x + y\n}\n"
    result = RustParser().parse(relative_path="lib.rs", content=content)

    assert len(result.functions) == 1
    function = result.functions[0]
    assert function.name == "add"
    assert function.parameters == ("x: i32", "y: i32")
    assert function.return_type == "i32"
    assert function.is_method is False


def test_parse_marks_async_functions() -> None:
    """`parse` should set `is_async=True` for an `async fn`."""
    result = RustParser().parse(
        relative_path="lib.rs", content="pub async fn fetch() -> i32 {\n    0\n}\n"
    )
    assert result.functions[0].is_async is True


def test_parse_does_not_count_a_free_function_inside_a_plain_mod_block_as_a_method() -> None:
    """`parse` should treat a function inside a plain `mod { ... }` block as a free function."""
    content = "mod internal {\n    pub fn helper() {}\n}\n"
    result = RustParser().parse(relative_path="lib.rs", content=content)

    assert [function.name for function in result.functions] == ["helper"]
    assert result.functions[0].is_method is False


def test_parse_exports_only_pub_declarations() -> None:
    """`parse` should export only declarations whose line starts with `pub`."""
    content = "pub fn exported() {}\n\nfn hidden() {}\n"
    result = RustParser().parse(relative_path="lib.rs", content=content)

    assert [export.name for export in result.exports] == ["exported"]


def test_parse_extracts_enum_and_type_alias_as_symbols() -> None:
    """`parse` should extract `enum` and `type` declarations into the symbol table."""
    content = "pub enum Color {\n    Red,\n    Green,\n}\n\npub type Meters = f64;\n"
    result = RustParser().parse(relative_path="lib.rs", content=content)

    kinds = {symbol.name: symbol.kind for symbol in result.symbols}
    assert kinds["Color"] is SymbolKind.ENUM
    assert kinds["Meters"] is SymbolKind.TYPE_ALIAS


def test_parse_reports_file_metadata() -> None:
    """`parse` should report line count, byte size, and a content hash."""
    content = "fn main() {}\n"
    result = RustParser().parse(relative_path="main.rs", content=content)

    assert result.metadata is not None
    assert result.metadata.language is SourceLanguage.RUST
    assert result.metadata.line_count == 1
    assert len(result.metadata.content_hash) == 64
