"""Unit tests for `src.parsers.go.parser`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.parsers.base import SymbolKind
from src.parsers.go.parser import GoParser


def test_language_is_go() -> None:
    """`GoParser.language` should report `SourceLanguage.GO`."""
    assert GoParser().language is SourceLanguage.GO


@pytest.mark.parametrize("path", ["main.go", "pkg/util.go", "Main.GO"])
def test_supports_accepts_go_extension(path: str) -> None:
    """`supports` should accept `.go` files, case-insensitively."""
    assert GoParser().supports(path) is True


@pytest.mark.parametrize("path", ["main.txt", "main.py"])
def test_supports_rejects_non_go_extensions(path: str) -> None:
    """`supports` should reject files without the Go extension."""
    assert GoParser().supports(path) is False


def test_parse_rejects_a_blank_relative_path() -> None:
    """`parse` should raise `ValidationError` for a blank `relative_path`."""
    with pytest.raises(ValidationError):
        GoParser().parse(relative_path="", content="package main")


def test_parse_succeeds_on_empty_content() -> None:
    """`parse` should succeed on an empty file."""
    result = GoParser().parse(relative_path="empty.go", content="")

    assert result.succeeded is True
    assert result.metadata is not None
    assert result.metadata.size_bytes == 0


def test_parse_extracts_the_package_clause_as_a_module() -> None:
    """`parse` should report the file's `package` clause as its one `ParsedModule`."""
    result = GoParser().parse(relative_path="main.go", content="package main\n")

    assert len(result.modules) == 1
    assert result.modules[0].name == "main"


def test_parse_extracts_grouped_imports_with_alias_and_blank() -> None:
    """`parse` should extract every import in a grouped `import ( ... )` block."""
    content = 'package main\n\nimport (\n\t"fmt"\n\tmyalias "some/pkg"\n\t_ "blank/import"\n)\n'
    result = GoParser().parse(relative_path="main.go", content=content)

    by_module = {imported.module: imported for imported in result.imports}
    assert by_module["fmt"].alias is None
    assert by_module["some/pkg"].alias == "myalias"
    assert by_module["blank/import"].alias is None


def test_parse_extracts_a_single_line_import() -> None:
    """`parse` should extract a single-line `import "path"` statement."""
    result = GoParser().parse(relative_path="main.go", content='package main\n\nimport "fmt"\n')

    assert len(result.imports) == 1
    assert result.imports[0].module == "fmt"


def test_parse_extracts_a_struct_as_a_class() -> None:
    """`parse` should report a `type ... struct` declaration as a `ParsedClass`."""
    content = "package main\n\ntype Point struct {\n\tX int\n\tY int\n}\n"
    result = GoParser().parse(relative_path="main.go", content=content)

    assert [cls.name for cls in result.classes] == ["Point"]


def test_parse_attaches_methods_to_their_receiver_struct() -> None:
    """`parse` should attach a method to its receiver struct, for both pointer and value forms."""
    content = (
        "package main\n\n"
        "type Point struct {\n\tX int\n}\n\n"
        "func (p *Point) Move(dx int) {\n}\n\n"
        "func (p Point) Read() int {\n\treturn p.X\n}\n"
    )
    result = GoParser().parse(relative_path="main.go", content=content)

    point = result.classes[0]
    assert {method.name for method in point.methods} == {"Move", "Read"}
    assert all(method.is_method for method in point.methods)


def test_parse_extracts_a_free_function_with_parameters_and_return() -> None:
    """`parse` should extract a top-level function's parameters and return type."""
    content = "package main\n\nfunc Add(x int, y int) (int, error) {\n\treturn x + y, nil\n}\n"
    result = GoParser().parse(relative_path="main.go", content=content)

    assert len(result.functions) == 1
    function = result.functions[0]
    assert function.name == "Add"
    assert function.parameters == ("x int", "y int")
    assert function.return_type == "(int, error)"
    assert function.is_method is False


def test_parse_handles_a_function_typed_parameter() -> None:
    """`parse` should not split a function-typed parameter's own parens as separate params."""
    content = "package main\n\nfunc Apply(x int, f func(int) string) string {\n\treturn f(x)\n}\n"
    result = GoParser().parse(relative_path="main.go", content=content)

    assert result.functions[0].parameters == ("x int", "f func(int) string")


def test_parse_classifies_const_and_var_correctly() -> None:
    """`parse` should classify `const` names as constants and `var` names as variables."""
    content = "package main\n\nconst MaxRetries = 3\nvar counter int\n"
    result = GoParser().parse(relative_path="main.go", content=content)

    kinds = {symbol.name: symbol.kind for symbol in result.symbols}
    assert kinds["MaxRetries"] is SymbolKind.CONSTANT
    assert kinds["counter"] is SymbolKind.VARIABLE


def test_parse_extracts_grouped_const_block_entries() -> None:
    """`parse` should extract every name in a grouped `const ( ... )` block."""
    content = "package main\n\nconst (\n\tA = iota\n\tB\n\tC\n)\n"
    result = GoParser().parse(relative_path="main.go", content=content)

    names = {symbol.name for symbol in result.symbols if symbol.kind is SymbolKind.CONSTANT}
    assert names == {"A", "B", "C"}


def test_parse_exports_only_capitalized_top_level_names() -> None:
    """`parse` should export only names starting with an uppercase letter."""
    content = (
        "package main\n\n"
        "func Exported() {}\n\n"
        "func unexported() {}\n\n"
        "const MaxValue = 1\n"
        "const minValue = 0\n"
    )
    result = GoParser().parse(relative_path="main.go", content=content)

    exported_names = {export.name for export in result.exports}
    assert exported_names == {"Exported", "MaxValue"}


def test_parse_extracts_an_interface_as_a_symbol_not_a_class() -> None:
    """`parse` should report an `interface` as an `INTERFACE` symbol, not a `ParsedClass`."""
    content = "package main\n\ntype Shape interface {\n\tArea() float64\n}\n"
    result = GoParser().parse(relative_path="main.go", content=content)

    assert result.classes == ()
    interfaces = [s for s in result.symbols if s.kind is SymbolKind.INTERFACE]
    assert [symbol.name for symbol in interfaces] == ["Shape"]


def test_parse_reports_file_metadata() -> None:
    """`parse` should report line count, byte size, and a content hash."""
    content = "package main\n"
    result = GoParser().parse(relative_path="main.go", content=content)

    assert result.metadata is not None
    assert result.metadata.language is SourceLanguage.GO
    assert result.metadata.line_count == 1
    assert len(result.metadata.content_hash) == 64
