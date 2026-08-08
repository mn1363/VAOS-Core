"""Unit tests for `src.parsers.typescript.parser`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.parsers.base import SymbolKind
from src.parsers.typescript.parser import TypeScriptParser


def test_language_is_typescript() -> None:
    """`TypeScriptParser.language` should report `SourceLanguage.TYPESCRIPT`."""
    assert TypeScriptParser().language is SourceLanguage.TYPESCRIPT


@pytest.mark.parametrize("path", ["main.ts", "component.tsx", "Main.TS"])
def test_supports_accepts_typescript_extensions(path: str) -> None:
    """`supports` should accept `.ts` and `.tsx` files, case-insensitively."""
    assert TypeScriptParser().supports(path) is True


@pytest.mark.parametrize("path", ["main.js", "main.py"])
def test_supports_rejects_non_typescript_extensions(path: str) -> None:
    """`supports` should reject files without a TypeScript extension."""
    assert TypeScriptParser().supports(path) is False


def test_parse_rejects_a_blank_relative_path() -> None:
    """`parse` should raise `ValidationError` for a blank `relative_path`."""
    with pytest.raises(ValidationError):
        TypeScriptParser().parse(relative_path="", content="const x = 1;")


def test_parse_succeeds_on_empty_content() -> None:
    """`parse` should succeed on an empty file."""
    result = TypeScriptParser().parse(relative_path="empty.ts", content="")
    assert result.succeeded is True
    assert result.metadata is not None


def test_parse_extracts_a_default_import() -> None:
    """`parse` should extract a default import, binding it via `alias`."""
    result = TypeScriptParser().parse(relative_path="a.ts", content='import Foo from "./foo";\n')

    imported = result.imports[0]
    assert imported.module == "./foo"
    assert imported.alias == "Foo"
    assert imported.is_relative is True


def test_parse_extracts_named_imports_with_aliases() -> None:
    """`parse` should extract each named import, with an alias when `as` is used."""
    result = TypeScriptParser().parse(
        relative_path="a.ts", content='import { A, B as C } from "./mod";\n'
    )

    named = {(i.imported_names, i.alias) for i in result.imports}
    assert (("A",), None) in named
    assert (("B",), "C") in named


def test_parse_extracts_a_namespace_import() -> None:
    """`parse` should extract `import * as N from "..."` as a wildcard import."""
    result = TypeScriptParser().parse(relative_path="a.ts", content='import * as NS from "./ns";\n')

    imported = result.imports[0]
    assert imported.imported_names == ("*",)
    assert imported.alias == "NS"


def test_parse_extracts_a_side_effect_only_import() -> None:
    """`parse` should extract a bare `import "./mod";` with no name or alias."""
    result = TypeScriptParser().parse(relative_path="a.ts", content='import "./side-effect";\n')

    imported = result.imports[0]
    assert imported.alias is None
    assert imported.imported_names == ()


def test_parse_extracts_a_class_with_extends_and_implements() -> None:
    """`parse` should combine `extends` and `implements` into `base_classes`."""
    content = "class Point extends Base implements Shape, Serializable {\n}\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert result.classes[0].base_classes == ("Base", "Shape", "Serializable")


def test_parse_extracts_class_methods_with_return_types() -> None:
    """`parse` should extract a class's methods, including a return type annotation."""
    content = "class Point {\n    distance(other: Point): number {\n        return 0;\n    }\n}\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    methods = result.classes[0].methods
    assert [m.name for m in methods] == ["distance"]
    assert methods[0].parameters == ("other: Point",)
    assert methods[0].return_type == "number"
    assert methods[0].is_method is True


def test_parse_does_not_mistake_a_call_statement_for_a_sibling_method() -> None:
    """`parse` should not treat a call statement inside a method body as its own method."""
    content = "class Foo {\n    bar() {\n        doSomething(a, b);\n    }\n}\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [m.name for m in result.classes[0].methods] == ["bar"]


def test_parse_extracts_jsdoc_as_class_docstring() -> None:
    """`parse` should collect a `/** ... */` block immediately above a class as its docstring."""
    content = "/**\n * A point in space.\n */\nclass Point {\n}\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert result.classes[0].docstring == "A point in space."


def test_parse_extracts_a_top_level_function_declaration() -> None:
    """`parse` should extract a top-level `function` declaration, including `async`."""
    content = "export async function fetchData(id: number): Promise<string> {\n    return '';\n}\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    function = result.functions[0]
    assert function.name == "fetchData"
    assert function.is_async is True
    assert function.return_type == "Promise<string>"
    assert function.is_method is False


def test_parse_extracts_an_arrow_function_assigned_to_const() -> None:
    """`parse` should recognize a `const name = (...) => {...}` as a function."""
    content = "const double = (x: number): number => {\n    return x * 2;\n};\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert len(result.functions) == 1
    function = result.functions[0]
    assert function.name == "double"
    assert function.parameters == ("x: number",)
    assert function.return_type == "number"


def test_parse_does_not_treat_a_plain_call_assignment_as_a_function() -> None:
    """`parse` should not treat `const x = someCall(a, b);` as a function declaration."""
    result = TypeScriptParser().parse(
        relative_path="a.ts", content="const notAFunction = someCall(1, 2);\n"
    )

    assert result.functions == ()


def test_parse_exports_a_function_marked_export() -> None:
    """`parse` should export a function whose declaration line starts with `export`."""
    result = TypeScriptParser().parse(
        relative_path="a.ts", content="export function foo() {}\n\nfunction hidden() {}\n"
    )

    assert [export.name for export in result.exports] == ["foo"]


def test_parse_extracts_export_brace_list_using_the_alias() -> None:
    """`parse` should use the alias, not the original name, for `export { A as B };`."""
    result = TypeScriptParser().parse(relative_path="a.ts", content="export { A, B as C };\n")

    export_names = {export.name for export in result.exports}
    assert export_names == {"A", "C"}


def test_parse_extracts_export_star() -> None:
    """`parse` should report `export * from "..."` as a wildcard export."""
    result = TypeScriptParser().parse(relative_path="a.ts", content='export * from "./other";\n')

    assert [export.name for export in result.exports] == ["*"]


def test_parse_reports_anonymous_default_export() -> None:
    """`parse` should report an anonymous `export default class {}` as `"default"`."""
    result = TypeScriptParser().parse(relative_path="a.ts", content="export default class {\n}\n")

    assert "default" in {export.name for export in result.exports}


def test_parse_extracts_interface_as_a_symbol_not_a_class() -> None:
    """`parse` should report an `interface` as an `INTERFACE` symbol, not a `ParsedClass`."""
    result = TypeScriptParser().parse(
        relative_path="a.ts", content="interface Shape {\n    area(): number;\n}\n"
    )

    assert result.classes == ()
    interfaces = [s for s in result.symbols if s.kind is SymbolKind.INTERFACE]
    assert [symbol.name for symbol in interfaces] == ["Shape"]


def test_parse_extracts_a_namespace_as_a_module() -> None:
    """`parse` should extract a `namespace { ... }` block as a `ParsedModule`."""
    result = TypeScriptParser().parse(
        relative_path="a.ts", content="namespace Utils {\n    export function helper() {}\n}\n"
    )

    assert [module.name for module in result.modules] == ["Utils"]


def test_parse_reports_file_metadata() -> None:
    """`parse` should report line count, byte size, and a content hash."""
    content = "const x = 1;\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert result.metadata is not None
    assert result.metadata.language is SourceLanguage.TYPESCRIPT
    assert result.metadata.line_count == 1
    assert len(result.metadata.content_hash) == 64
