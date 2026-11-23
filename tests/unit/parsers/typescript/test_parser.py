"""Unit tests for `src.parsers.typescript.parser`."""

import time

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.parsers.base import (
    ParsedFunction,
    ParsedProperty,
    SymbolKind,
    line_number_at,
    strip_c_style_comments,
)
from src.parsers.typescript.parser import (
    TypeScriptParser,
    _scan_typescript,
    strip_typescript_comments,
)


def _blank(text: str) -> str:
    """What a stripped comment becomes: spaces, with line feeds kept where they were."""
    return "".join("\n" if character == "\n" else " " for character in text)


def _interface_properties(content: str, index: int = 0) -> list[ParsedProperty]:
    """Parse `content` and return the properties of its `index`-th interface."""
    result = TypeScriptParser().parse(relative_path="ports.ts", content=content)
    return list(result.interfaces[index].properties)


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


def test_parse_extracts_ambient_function_declarations() -> None:
    """Ambient function signatures should use the shared ParsedFunction model."""
    content = """\
declare function parseValue<T>(input: string, strict?: boolean): T;
export declare function formatValue(value: number): string;
"""
    result = TypeScriptParser().parse(relative_path="api.d.ts", content=content)

    assert [(function.name, function.parameters, function.return_type) for function in result.functions] == [
        ("parseValue", ("input: string", "strict?: boolean"), "T"),
        ("formatValue", ("value: number",), "string"),
    ]
    assert {symbol.name for symbol in result.symbols if symbol.kind is SymbolKind.FUNCTION} == {
        "parseValue",
        "formatValue",
    }
    assert [export.name for export in result.exports] == ["formatValue"]


def test_parse_extracts_ambient_variables_classes_and_enums() -> None:
    """Ambient value and type declarations should use the existing symbol categories."""
    content = """\
declare const runtimeVersion: string;
export declare let currentMode: "safe" | "fast";
declare class ExternalClient<T> {
    connect(): Promise<T>;
}
export declare const enum Status { Ready, Failed }
"""
    result = TypeScriptParser().parse(relative_path="api.d.ts", content=content)

    symbol_pairs = {(symbol.name, symbol.kind) for symbol in result.symbols}
    assert ("runtimeVersion", SymbolKind.CONSTANT) in symbol_pairs
    assert ("currentMode", SymbolKind.VARIABLE) in symbol_pairs
    assert ("ExternalClient", SymbolKind.CLASS) in symbol_pairs
    assert ("Status", SymbolKind.ENUM) in symbol_pairs
    assert [cls.name for cls in result.classes] == ["ExternalClient"]
    assert [method.name for method in result.classes[0].methods] == ["connect"]
    assert {export.name for export in result.exports} == {"currentMode", "Status"}


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


def test_parse_extracts_ambient_module_and_global_augmentation_scopes() -> None:
    """Ambient module and global scopes must be transparent to declaration extraction."""
    content = """\
    declare module "external-package" {
        export interface ExternalShape {}
        export type ExternalId = string;
    }
    declare global {
        interface WindowExtension { value: string }
    }
    """

    result = TypeScriptParser().parse(relative_path="a.d.ts", content=content)

    assert [module.name for module in result.modules] == [
        "external-package",
        "global",
    ]
    assert {symbol.name for symbol in result.symbols} >= {
        "external-package",
        "global",
        "ExternalShape",
        "ExternalId",
        "WindowExtension",
    }


def test_parse_reports_file_metadata() -> None:
    """`parse` should report line count, byte size, and a content hash."""
    content = "const x = 1;\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert result.metadata is not None
    assert result.metadata.language is SourceLanguage.TYPESCRIPT
    assert result.metadata.line_count == 1
    assert len(result.metadata.content_hash) == 64

def test_parse_excludes_declarations_nested_in_executable_blocks() -> None:
    """Nested functions, values and local types must not leak into top-level results."""
    content = """\
function outer() {
    function nested() {}
    const localArrow = (value: number) => value;
    const localValue = 1;
    class LocalClass {}
    interface LocalShape {}
    type LocalAlias = string;
    enum LocalEnum { Value }
    if (true) {
        function callbackNested() {}
        const blockValue = 2;
    }
}
function visible() {}
const topArrow = (value: number) => value;
const topValue = 3;
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [function.name for function in result.functions] == ["outer", "visible", "topArrow"]
    assert [cls.name for cls in result.classes] == []
    symbol_pairs = {(symbol.name, symbol.kind) for symbol in result.symbols}
    assert ("topValue", SymbolKind.CONSTANT) in symbol_pairs
    assert not any(
        name in {"localValue", "blockValue", "LocalClass", "LocalShape", "LocalAlias", "LocalEnum"}
        for name, _ in symbol_pairs
    )


def test_parse_keeps_declarations_inside_namespace_scope() -> None:
    """Namespace/module scopes are transparent, but their nested executable scopes are opaque."""
    content = """\
namespace Utils {
    export function helper() {}
    export const version = 1;
    export const identity = (value: number) => value;
    export function outer() {
        function localHelper() {}
        const localValue = 2;
    }
}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [module.name for module in result.modules] == ["Utils"]
    assert [function.name for function in result.functions] == ["helper", "identity", "outer"]
    assert ("version", SymbolKind.CONSTANT) in {
        (symbol.name, symbol.kind) for symbol in result.symbols
    }
    assert not any(function.name == "localHelper" for function in result.functions)


def test_parse_keeps_same_name_top_level_class_and_function() -> None:
    """The parser must preserve both kinds so the frozen collision policy can reject them."""
    result = TypeScriptParser().parse(
        relative_path="a.ts", content="class Foo {}\nfunction Foo() {}\n"
    )

    assert [cls.name for cls in result.classes] == ["Foo"]
    assert [function.name for function in result.functions] == ["Foo"]


def test_parse_ignores_braces_inside_string_literals_when_tracking_scope() -> None:
    """A brace inside a string must not change whether later functions are file-scope."""
    result = TypeScriptParser().parse(
        relative_path="a.ts",
        content='const marker = "}";\nfunction visible() {}\n',
    )

    assert [function.name for function in result.functions] == ["visible"]


def test_parse_regex_apostrophe_does_not_hide_later_functions() -> None:
    """An apostrophe inside a regex literal must not start a string mask."""
    result = TypeScriptParser().parse(
        relative_path="a.ts",
        content="const re = /'/;\nfunction first() {}\nfunction second() {}\n",
    )
    assert [function.name for function in result.functions] == ["first", "second"]


def test_parse_unterminated_string_does_not_hide_later_lines() -> None:
    """An invalid single-line string must not mask the rest of the file."""
    result = TypeScriptParser().parse(
        relative_path="a.ts",
        content='const broken = "unterminated\nfunction visible() {}\n',
    )
    assert [function.name for function in result.functions] == ["visible"]

def test_parse_extracts_nested_ambient_scopes_and_global_declaration_kinds() -> None:
    """Nested ambient namespaces/modules and global declarations remain visible."""
    content = """\
declare namespace Outer {
    declare namespace Inner {
        export function nested(value: string): number;
        export const enabled: boolean;
    }
    declare module "sub-package" {
        export interface Shape {}
        export class Client {
            run(): void;
        }
    }
}
declare global {
    interface WindowExtension { appName: string; }
    function globalFunction(): void;
    const globalFlag: boolean;
    class GlobalClient {}
    enum GlobalState { Ready }
}
"""
    result = TypeScriptParser().parse(relative_path="nested.d.ts", content=content)

    assert [module.name for module in result.modules] == ["Outer", "Inner", "sub-package", "global"]
    symbol_pairs = {(symbol.name, symbol.kind) for symbol in result.symbols}
    assert ("Outer", SymbolKind.NAMESPACE) in symbol_pairs
    assert ("Inner", SymbolKind.NAMESPACE) in symbol_pairs
    assert ("sub-package", SymbolKind.NAMESPACE) in symbol_pairs
    assert ("Shape", SymbolKind.INTERFACE) in symbol_pairs
    assert ("WindowExtension", SymbolKind.INTERFACE) in symbol_pairs
    assert ("globalFunction", SymbolKind.FUNCTION) in symbol_pairs
    assert ("enabled", SymbolKind.CONSTANT) in symbol_pairs
    assert ("globalFlag", SymbolKind.CONSTANT) in symbol_pairs
    assert ("GlobalClient", SymbolKind.CLASS) in symbol_pairs
    assert ("GlobalState", SymbolKind.ENUM) in symbol_pairs
    client = next(cls for cls in result.classes if cls.name == "Client")
    assert [method.name for method in client.methods] == ["run"]

def test_parse_extracts_multiple_methods_from_single_line_class() -> None:
    """Class methods should be extracted when declarations share one source line."""
    content = "class Client { run(): void; stop(code: number): boolean; save(): number { return 1; } }\n"
    result = TypeScriptParser().parse(relative_path="client.d.ts", content=content)

    assert len(result.classes) == 1
    methods = result.classes[0].methods
    assert [(method.name, method.parameters, method.return_type) for method in methods] == [
        ("run", (), "void"),
        ("stop", ("code: number",), "boolean"),
        ("save", (), "number"),
    ]


def test_parse_does_not_extract_calls_inside_single_line_method_body() -> None:
    """Calls in a one-line method body must not become sibling class methods."""
    content = "class Client { run(): void { executeTask(value); } stop(): void {} }\n"
    result = TypeScriptParser().parse(relative_path="client.ts", content=content)

    assert [method.name for method in result.classes[0].methods] == ["run", "stop"]

def test_parse_extracts_accessors_and_optional_methods() -> None:
    """Getters, setters, and optional methods are class method declarations."""
    content = """class Client {
    get value(): string { return ""; }
    set value(input: string) {}
    run?(): void;
}
"""
    result = TypeScriptParser().parse(relative_path="client.ts", content=content)

    assert [(method.name, method.parameters, method.return_type) for method in result.classes[0].methods] == [
        ("value", (), "string"),
        ("value", ("input: string",), None),
        ("run", (), "void"),
    ]


def test_parse_extracts_methods_with_nested_generic_parameters() -> None:
    """Nested generic delimiters must not hide a method declaration."""
    content = """class Client<T extends Record<string, Array<number>>> {
    map<U extends Record<string, Array<T>>>(value: U): Promise<Array<U>>;
}
"""
    result = TypeScriptParser().parse(relative_path="client.ts", content=content)

    assert len(result.classes) == 1
    assert result.classes[0].name == "Client"
    assert [(method.name, method.parameters, method.return_type) for method in result.classes[0].methods] == [
        ("map", ("value: U",), "Promise<Array<U>>"),
    ]


def test_parse_extracts_interface_method_signatures() -> None:
    """Interfaces expose ordinary, optional, generic, getter, and setter signatures."""
    content = """interface Repository<T> extends BaseRepository<T> {
    find(id: string): Promise<T>;
    save?(value: T): void;
    map<U extends Record<string, Array<T>>>(value: U): Promise<Array<U>>;
    get size(): number;
    set size(value: number);
}
"""
    result = TypeScriptParser().parse(relative_path="repository.d.ts", content=content)

    assert len(result.interfaces) == 1
    interface = result.interfaces[0]
    assert interface.name == "Repository"
    assert [(method.name, method.parameters, method.return_type) for method in interface.methods] == [
        ("find", ("id: string",), "Promise<T>"),
        ("save", ("value: T",), "void"),
        ("map", ("value: U",), "Promise<Array<U>>"),
        ("size", (), "number"),
        ("size", ("value: number",), None),
    ]
    method_symbols = [symbol.name for symbol in result.symbols if symbol.kind == SymbolKind.METHOD]
    assert method_symbols == ["find", "save", "map", "size", "size"]


def test_parse_extracts_required_interface_properties() -> None:
    """Plain `name: Type` members are required, writable properties."""
    content = """interface User {
    id: string;
    name: string;
}
"""
    assert _interface_properties(content) == [
        ParsedProperty(name="id", type_annotation="string", line_number=2),
        ParsedProperty(name="name", type_annotation="string", line_number=3),
    ]


def test_parse_extracts_optional_interface_properties() -> None:
    """`name?: Type` members are optional and nothing else changes."""
    content = "interface User {\n    age?: number;\n    nickname ?: string;\n}\n"

    assert _interface_properties(content) == [
        ParsedProperty(name="age", type_annotation="number", is_optional=True, line_number=2),
        ParsedProperty(name="nickname", type_annotation="string", is_optional=True, line_number=3),
    ]


def test_parse_extracts_readonly_interface_properties() -> None:
    """`readonly` is recorded as a modifier and is not part of the name or the type."""
    content = "interface User {\n    readonly createdAt: Date;\n}\n"

    assert _interface_properties(content) == [
        ParsedProperty(name="createdAt", type_annotation="Date", is_readonly=True, line_number=2)
    ]


def test_parse_extracts_optional_readonly_interface_properties() -> None:
    """A property can be both `readonly` and optional."""
    content = "interface User {\n    readonly tags?: string[];\n}\n"

    assert _interface_properties(content) == [
        ParsedProperty(
            name="tags",
            type_annotation="string[]",
            is_optional=True,
            is_readonly=True,
            line_number=2,
        )
    ]


def test_parse_extracts_the_documented_user_interface() -> None:
    """The `User` interface from the task description yields its five properties."""
    content = """interface User {
    id: string;
    name: string;
    age?: number;
    readonly createdAt: Date;
    readonly tags?: string[];
}
"""
    properties = _interface_properties(content)

    assert [
        (p.name, p.type_annotation, p.is_optional, p.is_readonly) for p in properties
    ] == [
        ("id", "string", False, False),
        ("name", "string", False, False),
        ("age", "number", True, False),
        ("createdAt", "Date", False, True),
        ("tags", "string[]", True, True),
    ]


def test_parse_extracts_generic_interface_properties_next_to_a_method() -> None:
    """A generic interface keeps its properties and its optional method separate."""
    content = """interface Repository<T> {
    items: T[];
    readonly metadata: Record<string, unknown>;
    findById?(id: string): Promise<T>;
}
"""
    result = TypeScriptParser().parse(relative_path="repository.ts", content=content)

    interface = result.interfaces[0]
    assert interface.name == "Repository"
    assert interface.properties == (
        ParsedProperty(name="items", type_annotation="T[]", line_number=2),
        ParsedProperty(
            name="metadata",
            type_annotation="Record<string, unknown>",
            is_readonly=True,
            line_number=3,
        ),
    )
    assert [(m.name, m.return_type) for m in interface.methods] == [("findById", "Promise<T>")]


def test_parse_keeps_nested_generic_property_types_intact() -> None:
    """Commas and `>` inside nested generics must not split or truncate the type."""
    content = """interface Cache {
    entries: Map<string, Array<Record<string, number>>>, size: number;
    lookup: Promise<Map<string, Set<Array<number>>>>;
    after: boolean;
}
"""
    assert [(p.name, p.type_annotation) for p in _interface_properties(content)] == [
        ("entries", "Map<string, Array<Record<string, number>>>"),
        ("size", "number"),
        ("lookup", "Promise<Map<string, Set<Array<number>>>>"),
        ("after", "boolean"),
    ]


def test_parse_keeps_arrow_function_generic_arguments_balanced() -> None:
    """The `>` of `=>` inside a generic argument must not close an angle bracket early."""
    content = """interface Bus {
    handlers: Array<(event: Event) => void>, count: number;
    next: string;
}
"""
    assert [(p.name, p.type_annotation) for p in _interface_properties(content)] == [
        ("handlers", "Array<(event: Event) => void>"),
        ("count", "number"),
        ("next", "string"),
    ]


def test_parse_extracts_union_and_intersection_property_types() -> None:
    """Union and intersection operators are part of the type, not member separators."""
    content = """interface Shape {
    kind: "circle" | "square" | null;
    box: Sized & Positioned;
    mixed: (A | B) & C;
}
"""
    assert [(p.name, p.type_annotation) for p in _interface_properties(content)] == [
        ("kind", '"circle" | "square" | null'),
        ("box", "Sized & Positioned"),
        ("mixed", "(A | B) & C"),
    ]


def test_parse_extracts_multiline_union_property_types() -> None:
    """A union continued on following lines stays one property."""
    content = """interface Job {
    status:
        | "queued"
        | "running"
        | "done";
    id: string
}
"""
    properties = _interface_properties(content)

    assert [(p.name, p.type_annotation, p.line_number) for p in properties] == [
        ("status", '| "queued" | "running" | "done"', 2),
        ("id", "string", 6),
    ]


def test_parse_extracts_array_and_tuple_property_types() -> None:
    """Array shorthand, generic arrays, tuples, and readonly arrays are kept as written."""
    content = """interface Lists {
    names: string[];
    ids: Array<number>;
    pair: [string, number];
    frozen: readonly boolean[];
    grid: number[][];
}
"""
    assert [(p.name, p.type_annotation) for p in _interface_properties(content)] == [
        ("names", "string[]"),
        ("ids", "Array<number>"),
        ("pair", "[string, number]"),
        ("frozen", "readonly boolean[]"),
        ("grid", "number[][]"),
    ]


def test_parse_extracts_function_and_object_property_types() -> None:
    """Function and object types are properties; their inner members are not."""
    content = """interface Widget {
    onChange: (value: string, done: (ok: boolean) => void) => void;
    meta: { id: string; run(): void; nested?: { deep: number } };
    factory: new (name: string) => Widget;
    after: number;
}
"""
    result = TypeScriptParser().parse(relative_path="widget.ts", content=content)

    interface = result.interfaces[0]
    assert [(p.name, p.type_annotation) for p in interface.properties] == [
        ("onChange", "(value: string, done: (ok: boolean) => void) => void"),
        ("meta", "{ id: string; run(): void; nested?: { deep: number } }"),
        ("factory", "new (name: string) => Widget"),
        ("after", "number"),
    ]
    assert interface.methods == ()


def test_parse_extracts_string_and_numeric_property_names() -> None:
    """Quoted names lose their quotes; numeric names are kept as written."""
    content = """interface Headers {
    "content-type": string;
    'x-id'?: number;
    0: boolean;
    1.5: string;
    "has;semi,colon{brace": string;
}
"""
    assert [
        (p.name, p.type_annotation, p.is_optional) for p in _interface_properties(content)
    ] == [
        ("content-type", "string", False),
        ("x-id", "number", True),
        ("0", "boolean", False),
        ("1.5", "string", False),
        ("has;semi,colon{brace", "string", False),
    ]


def test_parse_extracts_multiple_properties_on_one_line() -> None:
    """Semicolon- and comma-separated members sharing a line are separate properties."""
    content = "interface P { a: string; b?: number, readonly c: boolean; d: Date }\n"

    properties = _interface_properties(content)

    assert [(p.name, p.type_annotation, p.is_optional, p.is_readonly) for p in properties] == [
        ("a", "string", False, False),
        ("b", "number", True, False),
        ("c", "boolean", False, True),
        ("d", "Date", False, False),
    ]
    assert {p.line_number for p in properties} == {1}


def test_parse_extracts_newline_separated_properties_without_separators() -> None:
    """Members separated only by line breaks are still separate properties."""
    content = "interface P {\n    a: string\n    b: number\n    c: boolean\n}\n"

    assert [(p.name, p.type_annotation) for p in _interface_properties(content)] == [
        ("a", "string"),
        ("b", "number"),
        ("c", "boolean"),
    ]


def test_parse_extracts_properties_with_comments_and_whitespace() -> None:
    """Comments are ignored and whitespace inside a type is collapsed."""
    content = """interface Noisy {
    // a leading comment: with a colon; and a semicolon
    id   :   string ;   // trailing comment, with a comma
    /* block; comment */ name?:\tstring   /* inline */   |   null;
    /**
     * Documented.
     */
    readonly   created :  Date
}
"""
    properties = _interface_properties(content)

    assert [
        (p.name, p.type_annotation, p.is_optional, p.is_readonly, p.line_number)
        for p in properties
    ] == [
        ("id", "string", False, False, 3),
        ("name", "string | null", True, False, 4),
        ("created", "Date", False, True, 8),
    ]


def test_parse_reports_the_line_each_property_is_declared_on() -> None:
    """`line_number` is the 1-indexed line of each property, even after blank lines."""
    content = """\
import { Date } from "./date";

interface User {
    id: string;

    name: string;
    readonly createdAt: Date;
}
"""
    properties = _interface_properties(content)

    assert [(p.name, p.line_number) for p in properties] == [
        ("id", 4),
        ("name", 6),
        ("createdAt", 7),
    ]


def test_parse_keeps_properties_and_methods_of_one_interface_separate() -> None:
    """Properties, methods, accessors and signatures must each land in their own place."""
    content = """interface Mixed {
    id: string;
    find(id: string): Promise<string>;
    save?(value: string): void;
    map<U>(value: U): Array<U>;
    get size(): number;
    set size(value: number);
    (call: number): string;
    new (ctor: number): Mixed;
    [key: string]: unknown;
    <T>(generic: T): T;
    label?: string;
}
"""
    result = TypeScriptParser().parse(relative_path="mixed.ts", content=content)

    interface = result.interfaces[0]
    assert [(p.name, p.line_number) for p in interface.properties] == [("id", 2), ("label", 12)]
    assert [m.name for m in interface.methods] == ["find", "save", "map", "size", "size", "new"]
    property_symbols = [s.name for s in result.symbols if s.kind is SymbolKind.PROPERTY]
    assert property_symbols == ["id", "label"]


@pytest.mark.parametrize(
    ("member", "is_property"),
    [
        ("find(id: string): void", False),
        ("find?(id: string): void", False),
        ("find<T>(id: T): void", False),
        ("get value(): string", False),
        ("set value(next: string)", False),
        ("(input: string): number", False),
        ("new (input: string): Thing", False),
        ("<T>(input: T): T", False),
        ("[key: string]: number", False),
        ("readonly [key: string]: number", False),
        ("[Symbol.iterator]: Iterator<number>", False),
        ("value: string", True),
        ("get: string", True),
        ("set?: string", True),
        ("readonly: boolean", True),
        ("new: string", True),
    ],
)
def test_parse_classifies_interface_members(member: str, is_property: bool) -> None:
    """Only data properties become properties; every other member shape is left out."""
    content = f"interface Probe {{\n    {member};\n}}\n"

    assert bool(_interface_properties(content)) is is_property


def test_parse_treats_get_set_new_and_readonly_names_as_ordinary_properties() -> None:
    """Contextual keywords used as property names keep their own name and flags."""
    content = """interface Names {
    get: string;
    set?: number;
    new: boolean;
    readonly: Date;
    readonly readonly: Date;
}
"""
    assert [
        (p.name, p.type_annotation, p.is_optional, p.is_readonly)
        for p in _interface_properties(content)
    ] == [
        ("get", "string", False, False),
        ("set", "number", True, False),
        ("new", "boolean", False, False),
        ("readonly", "Date", False, False),
        ("readonly", "Date", False, True),
    ]


def test_parse_extracts_a_property_without_a_type_annotation() -> None:
    """An implicitly typed member has no type annotation but is still a property."""
    content = "interface Loose {\n    anything;\n    maybe?;\n}\n"

    assert _interface_properties(content) == [
        ParsedProperty(name="anything", line_number=2),
        ParsedProperty(name="maybe", is_optional=True, line_number=3),
    ]


def test_parse_keeps_same_named_properties_of_different_interfaces_separate() -> None:
    """Each interface owns its own properties, even when the names are identical."""
    content = """interface Reader {
    id: string;
    name: string;
}
interface Writer {
    id: number;
}
"""
    result = TypeScriptParser().parse(relative_path="ports.ts", content=content)

    assert [(i.name, [(p.name, p.type_annotation) for p in i.properties]) for i in result.interfaces] == [
        ("Reader", [("id", "string"), ("name", "string")]),
        ("Writer", [("id", "number")]),
    ]
    assert [s.name for s in result.symbols if s.kind is SymbolKind.PROPERTY] == [
        "id",
        "name",
        "id",
    ]


def test_parse_keeps_duplicate_property_declarations_in_order() -> None:
    """Duplicate names inside one interface are preserved, never merged."""
    content = "interface Dup {\n    id: string;\n    id: number;\n}\n"

    assert [(p.name, p.type_annotation, p.line_number) for p in _interface_properties(content)] == [
        ("id", "string", 2),
        ("id", "number", 3),
    ]


def test_parse_does_not_leak_nested_object_type_members_as_properties() -> None:
    """Members of an inline object type belong to that type, not to the interface."""
    content = """interface Outer {
    inner: {
        hidden: string;
        deeper: { deepest: number };
    };
    visible: boolean;
}
"""
    assert [p.name for p in _interface_properties(content)] == ["inner", "visible"]


def test_parse_ignores_braces_and_quotes_inside_property_string_literals() -> None:
    """Braces and separators in string literal types must not end the interface or a member."""
    content = """interface Tokens {
    open: "{";
    close: "}";
    pair: "a;b,c";
    template: `x${string}y`;
    last: number;
}
interface Next {
    value: string;
}
"""
    result = TypeScriptParser().parse(relative_path="tokens.ts", content=content)

    assert [i.name for i in result.interfaces] == ["Tokens", "Next"]
    assert [(p.name, p.type_annotation) for p in result.interfaces[0].properties] == [
        ("open", '"{"'),
        ("close", '"}"'),
        ("pair", '"a;b,c"'),
        ("template", "`x${string}y`"),
        ("last", "number"),
    ]
    assert [p.name for p in result.interfaces[1].properties] == ["value"]


def test_parse_extracts_properties_of_interfaces_inside_namespaces() -> None:
    """Namespace scopes are transparent, so their interfaces' properties are extracted too."""
    content = """namespace Models {
    export interface Item {
        readonly sku: string;
        price?: number;
    }
}
"""
    properties = _interface_properties(content)

    assert [(p.name, p.is_readonly, p.is_optional, p.line_number) for p in properties] == [
        ("sku", True, False, 3),
        ("price", False, True, 4),
    ]


def test_parse_does_not_extract_properties_of_nested_or_local_interfaces() -> None:
    """Interfaces declared inside function bodies stay out, along with their properties."""
    content = """function build() {
    interface Local {
        hidden: string;
    }
}
interface Visible {
    shown: string;
}
"""
    result = TypeScriptParser().parse(relative_path="scoped.ts", content=content)

    assert [i.name for i in result.interfaces] == ["Visible"]
    assert [s.name for s in result.symbols if s.kind is SymbolKind.PROPERTY] == ["shown"]


def test_parse_reports_an_interface_without_properties_as_having_none() -> None:
    """Interfaces with only methods, or empty bodies, have no properties."""
    content = "interface OnlyMethods {\n    run(): void;\n}\ninterface Empty {}\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [(i.name, i.properties) for i in result.interfaces] == [
        ("OnlyMethods", ()),
        ("Empty", ()),
    ]


def test_parse_reports_interface_properties_in_the_flat_symbol_table() -> None:
    """Each property also appears as a `PROPERTY` symbol with the property's own line."""
    content = "interface User {\n    id: string;\n    readonly tags?: string[];\n}\n"
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    properties = [(s.name, s.line_number) for s in result.symbols if s.kind is SymbolKind.PROPERTY]
    assert properties == [("id", 2), ("tags", 3)]
    assert [(s.name, s.kind) for s in result.symbols if s.name == "User"] == [
        ("User", SymbolKind.INTERFACE)
    ]


def test_parse_interface_methods_are_unchanged_by_property_extraction() -> None:
    """Regression: the method-only interface from the method tests parses exactly as before."""
    content = """interface Repository<T> extends BaseRepository<T> {
    find(id: string): Promise<T>;
    save?(value: T): void;
    map<U extends Record<string, Array<T>>>(value: U): Promise<Array<U>>;
    get size(): number;
    set size(value: number);
}
"""
    result = TypeScriptParser().parse(relative_path="repository.d.ts", content=content)

    interface = result.interfaces[0]
    assert interface.properties == ()
    assert interface.line_number == 1
    assert [(m.name, m.parameters, m.return_type, m.line_number) for m in interface.methods] == [
        ("find", ("id: string",), "Promise<T>", 2),
        ("save", ("value: T",), "void", 3),
        ("map", ("value: U",), "Promise<Array<U>>", 4),
        ("size", (), "number", 5),
        ("size", ("value: number",), None, 6),
    ]
    assert not [s for s in result.symbols if s.kind is SymbolKind.PROPERTY]


def test_parse_does_not_mistake_property_type_text_for_a_method() -> None:
    """A construct type such as `new (...) => T` inside a property type is not a method."""
    content = "interface Factory {\n    ctor: new (name: string) => Factory;\n    build(): void;\n}\n"
    result = TypeScriptParser().parse(relative_path="factory.ts", content=content)

    assert [m.name for m in result.interfaces[0].methods] == ["build"]
    assert [p.name for p in result.interfaces[0].properties] == ["ctor"]


def test_parse_does_not_change_class_extraction_for_property_like_class_members() -> None:
    """Classes keep their existing behavior: fields are not interface properties."""
    content = "class Box {\n    size: number = 1;\n    grow(): void {}\n}\n"
    result = TypeScriptParser().parse(relative_path="box.ts", content=content)

    assert result.interfaces == ()
    assert [m.name for m in result.classes[0].methods] == ["grow"]
    assert not [s for s in result.symbols if s.kind is SymbolKind.PROPERTY]


# --- comment stripping -------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        'x: "http://example.com";',
        "x: 'http://example.com';",
        'x: "/* text */";',
        "x: '/* text */';",
        'x: "a \\" // b";',
        "x: 'it\\'s // fine';",
        "x: `http://example.com`;",
        "x: `/* text */`;",
        'x: "a" | "b//c" | \'d/*e*/\';',
    ],
)
def test_strip_typescript_comments_leaves_comment_markers_inside_literals_alone(
    content: str,
) -> None:
    """Strings and templates are returned untouched, whatever comment markers they contain."""
    assert strip_typescript_comments(content) == content


def test_strip_typescript_comments_blanks_a_line_comment_after_a_property() -> None:
    """A real `//` comment is blanked, and a quote inside it does not start a string."""
    comment = "// note with a \"quote and 'apostrophe"
    content = f"a: string; {comment}\nb: \"x//y\";\n"

    assert strip_typescript_comments(content) == f"a: string; {_blank(comment)}\nb: \"x//y\";\n"


def test_strip_typescript_comments_blanks_a_block_comment_between_properties() -> None:
    """A real multi-line block comment is blanked but keeps its line feeds."""
    comment = '/* first\nsecond "quote\nthird */'
    content = f"a: string;\n{comment}\nb: number;\n"

    result = strip_typescript_comments(content)

    assert result == f"a: string;\n{_blank(comment)}\nb: number;\n"
    assert result.count("\n") == content.count("\n")


def test_strip_typescript_comments_handles_comments_and_strings_on_one_line() -> None:
    """Literals and comments interleaved on one line are each told apart correctly."""
    first, second, third = "/* c */", "/* second */", "// end 'tail"
    content = f'a: "x//y"; {first} b: \'/*z*/\'; {second} c: "q"; {third}'

    assert strip_typescript_comments(content) == (
        f'a: "x//y"; {_blank(first)} b: \'/*z*/\'; {_blank(second)} c: "q"; {_blank(third)}'
    )


def test_strip_typescript_comments_honors_an_escaped_backslash_before_the_closing_quote() -> None:
    """`\\\\` escapes only the backslash, so the next quote still closes the string."""
    comment = "// real comment"
    content = f'x: "tail \\\\"; {comment}'

    assert strip_typescript_comments(content) == f'x: "tail \\\\"; {_blank(comment)}'


def test_strip_typescript_comments_ends_an_unclosed_string_at_the_line_break() -> None:
    """A string missing its closing quote must not swallow the comments on later lines."""
    comment = "// later comment"
    content = f'x = "unclosed\n{comment}\ny = 1;'

    assert strip_typescript_comments(content) == f'x = "unclosed\n{_blank(comment)}\ny = 1;'


def test_strip_typescript_comments_does_not_start_a_string_inside_a_regex_literal() -> None:
    """A quote inside a regular-expression literal must not hide the comment after it."""
    comment = "// tail 'quote"
    content = f"const quote = /'/g; {comment}\nconst double = /\"/; {comment}"

    assert strip_typescript_comments(content) == (
        f"const quote = /'/g; {_blank(comment)}\nconst double = /\"/; {_blank(comment)}"
    )


def test_strip_typescript_comments_leaves_comment_markers_in_template_text_alone() -> None:
    """Template literal text keeps `//` and `/*`, including around an interpolation."""
    content = "x: `http://${host}/a//b`; y: `/* ${a} */`;"

    assert strip_typescript_comments(content) == content


def test_strip_typescript_comments_treats_template_interpolation_as_code() -> None:
    """A comment inside `${...}` is stripped, while the template text around it is kept."""
    inner, trailing = "/* inner */", "// real"
    content = f"x: `${{{inner} a}}// kept`; {trailing}"

    assert strip_typescript_comments(content) == (
        f"x: `${{{_blank(inner)} a}}// kept`; {_blank(trailing)}"
    )


@pytest.mark.parametrize(
    "content",
    [
        'x: `${"}"}//kept`;',
        "x: `${ {a: 1}.a }//kept`;",
        "x: `${`//inner`}//outer`;",
        "x: `a\\`//b`;",
        "x: `a\\${//b}`;",
    ],
)
def test_strip_typescript_comments_tracks_interpolation_and_escapes(content: str) -> None:
    """Braces in strings or objects, nested templates, and escapes do not end a template early."""
    assert strip_typescript_comments(content) == content


def test_strip_typescript_comments_runs_an_unclosed_template_to_the_end_of_the_file() -> None:
    """Documented limitation: an unclosed template literal hides everything after it."""
    content = "x = `abc // not a comment\n// also kept\n"

    assert strip_typescript_comments(content) == content


def test_strip_typescript_comments_preserves_offsets_and_line_numbers() -> None:
    """Length, every line feed, and every non-comment character stay exactly where they were."""
    content = (
        "// header\n"
        "interface Config {\n"
        '    endpoint: "http://example.com"; // trailing\n'
        "    /* multi\n"
        "       line */\n"
        '    pattern: "/* kept */";\n'
        "    marker: `//${1}/*`; /* x */ other: string;\n"
        "}\n"
    )

    result = strip_typescript_comments(content)

    assert len(result) == len(content)
    assert [i for i, c in enumerate(result) if c == "\n"] == [
        i for i, c in enumerate(content) if c == "\n"
    ]
    assert all(r == o or r == " " for r, o in zip(result, content, strict=True))
    for marker in ("interface Config", "endpoint", "pattern", "marker", "other", "}"):
        assert result.index(marker) == content.index(marker)
        assert line_number_at(result, result.index(marker)) == line_number_at(
            content, content.index(marker)
        )
    assert "header" not in result
    assert "trailing" not in result
    assert "multi" not in result
    assert "x */" not in result


def test_strip_typescript_comments_matches_the_shared_scanner_without_literals() -> None:
    """Without string, template, or regex content, the result is identical to the shared one."""
    content = (
        "// line\r\nclass A {} /* block\r\n spanning */ const a = 1; // tail\r\n"
        "interface B { c: number } /* unterminated\r\nstill comment"
    )

    assert strip_typescript_comments(content) == strip_c_style_comments(content)


def test_parse_keeps_string_literal_property_types_that_contain_comment_markers() -> None:
    """Regression: `//` and `/*` inside string types no longer truncate or corrupt a property."""
    content = """interface Config {
    endpoint: "http://example.com";
    mirror: 'http://example.org';
    pattern: "/* not a comment */";
    quoted: "say \\"//hi\\"";   // a real comment
    /* a real block
       comment */
    template: `http://${string}/path`;
    last: number; // trailing
}
export const VERSION = 1;
interface After {
    ok: boolean;
}
"""
    result = TypeScriptParser().parse(relative_path="config.ts", content=content)

    assert [i.name for i in result.interfaces] == ["Config", "After"]
    assert [(p.name, p.type_annotation, p.line_number) for p in result.interfaces[0].properties] == [
        ("endpoint", '"http://example.com"', 2),
        ("mirror", "'http://example.org'", 3),
        ("pattern", '"/* not a comment */"', 4),
        ("quoted", '"say \\"//hi\\""', 5),
        ("template", "`http://${string}/path`", 8),
        ("last", "number", 9),
    ]
    assert [p.name for p in result.interfaces[1].properties] == ["ok"]
    assert [(s.name, s.line_number) for s in result.symbols if s.name == "VERSION"] == [
        ("VERSION", 11)
    ]


def test_parse_still_ignores_declarations_and_braces_inside_real_comments() -> None:
    """Regression: real comments are still blanked, so lookalike declarations in them are not found."""
    content = """// interface Hidden { a: string }
/* interface AlsoHidden {
   b: string
*/
interface Shown {
    a: "x//y"; // interface Trailing { c: string }
}
"""
    result = TypeScriptParser().parse(relative_path="comments.ts", content=content)

    assert [i.name for i in result.interfaces] == ["Shown"]
    assert [(p.name, p.type_annotation) for p in result.interfaces[0].properties] == [
        ("a", '"x//y"')
    ]


# --- nested template literals: the two scanning passes must agree ------------------------


@pytest.mark.parametrize(
    "declaration",
    [
        "const a = `${`{`}`;",
        "const a = `${`}`}`;",
        "const a = `x${`y${z}{`}w`;",
        'const a = `${"`"}{`;',
        "const a = `${ /* ` { */ 1 }`;",
        "const a = `${ '}' + \"{\" }`;",
        "const a = `a\\`{b`;",
        "const a = `a\\${ {b`;",
        "const a = `${ {a: 1}.a }{`;",
        "const a = `${/}/.test(s)}{`;",
    ],
)
def test_parse_finds_the_interface_after_a_template_literal_with_hidden_braces(
    declaration: str,
) -> None:
    """Braces inside (nested) template text or expressions never reach the depth analysis."""
    content = f"{declaration}\ninterface After {{\n    a: string;\n}}\n"

    result = TypeScriptParser().parse(relative_path="t.ts", content=content)

    assert [i.name for i in result.interfaces] == ["After"]
    assert [p.name for p in result.interfaces[0].properties] == ["a"]


def test_parse_keeps_a_local_interface_out_after_a_nested_template_with_a_close_brace() -> None:
    """A `}` in nested template text must not close the enclosing function body early."""
    content = """function render() {
    const t = `${`}`}{`;
    interface Hidden { x: string }
}
interface After { a: string }
"""
    result = TypeScriptParser().parse(relative_path="t.ts", content=content)

    assert [i.name for i in result.interfaces] == ["After"]


def test_parse_extracts_interface_properties_with_nested_template_literal_types() -> None:
    """Nested templates, braces, and separators inside a property type stay inside that type."""
    content = """interface Routes {
    path: `/api/${`v${number}`}/items`;
    nested: `${`{`}`;
    brace: `}${`{${string}}`}`;
    sep: `a${`;,`}b`, comma: number
    after: string; // real comment
}
interface Next {
    ok: boolean;
}
"""
    result = TypeScriptParser().parse(relative_path="routes.ts", content=content)

    assert [i.name for i in result.interfaces] == ["Routes", "Next"]
    assert [(p.name, p.type_annotation, p.line_number) for p in result.interfaces[0].properties] == [
        ("path", "`/api/${`v${number}`}/items`", 2),
        ("nested", "`${`{`}`", 3),
        ("brace", "`}${`{${string}}`}`", 4),
        ("sep", "`a${`;,`}b`", 5),
        ("comma", "number", 5),
        ("after", "string", 6),
    ]
    assert [p.name for p in result.interfaces[1].properties] == ["ok"]



def _visible_braces(structural_scan: str) -> str:
    """The `{` and `}` characters that survive literal masking, in order."""
    return "".join(character for character in structural_scan if character in "{}")


@pytest.mark.parametrize(
    ("content", "visible"),
    [
        ("x = `${`{`}`;", ""),
        ("x = `${`}`}`;", ""),
        ("x = `a${`b${c}{`}w`;", ""),
        ("x = `${`${`{${y}}`}`}`;", ""),
        ('x = `${"`"}{`;', ""),
        ("x = `${ '}' + \"{\" }`;", ""),
        ("x = `${ {a: 1}.a }{`;", ""),
        ("x = `${ ((v) => { return v; })(1) }`;", ""),
        ("x = `a\\`{b`;", ""),
        ("x = `a\\${ {b`;", ""),
        ("x = `${`a\\`{`}`;", ""),
        ("x = `${/}/.test(s)}{`;", ""),
        ("x = `${ /* ` { */ 1 }`;", ""),
        ("x = `${ 1 // ` {\n}`;", ""),
        ('x = ["{", \'}\', /{/];', ""),
        ("function f() { return `${`{`}`; }", "{}"),
        ("if (a) { x = `}${`{`}`; } else { y = 1; }", "{}{}"),
    ],
)
def test_scan_masks_exactly_the_literals_and_leaves_code_braces_visible(
    content: str, visible: str
) -> None:
    """Both scan halves agree: literal braces vanish, braces in real code remain."""
    scan, structural = _scan_typescript(content)

    assert _visible_braces(structural) == visible
    assert scan == strip_typescript_comments(content)
    assert len(scan) == len(structural) == len(content)
    assert all(m == s or m == "\x00" for m, s in zip(structural, scan, strict=True))


def test_scan_masks_a_whole_nested_template_including_its_expressions() -> None:
    """The outer template and everything nested in it is one masked extent."""
    template = "`a${`b${c}d`}e`"
    content = f"x = {template};\ny = 1;"

    scan, structural = _scan_typescript(content)

    assert scan == content
    assert structural == f"x = {chr(0) * len(template)};\ny = 1;"


def test_scan_masks_a_multiline_template_but_keeps_every_line_break() -> None:
    """Line feeds and carriage returns survive masking, so offsets and line numbers hold."""
    content = "x = `a${\r\n  `b{`\r\n}c`;\r\ny = 2;\r\n"

    scan, structural = _scan_typescript(content)

    assert scan == content
    assert len(structural) == len(content)
    assert [i for i, c in enumerate(structural) if c == "\n"] == [
        i for i, c in enumerate(content) if c == "\n"
    ]
    assert structural.count("\r") == content.count("\r") == 4
    assert _visible_braces(structural) == ""
    assert structural.endswith(";\r\ny = 2;\r\n")


def test_scan_strips_comments_inside_nested_expressions_and_masks_the_template() -> None:
    """A comment in expression code is blanked in `scan`; the template is masked as a whole."""
    inner, outer, trailing = "/* c1 ` { */", "// c2 ` }", "// real"
    content = f"x = `${{ {inner} `t${{ y {outer}\n }}` }}`; {trailing}\nz = 1;"

    scan, structural = _scan_typescript(content)

    assert scan == (
        f"x = `${{ {_blank(inner)} `t${{ y {_blank(outer)}\n }}` }}`; {_blank(trailing)}\nz = 1;"
    )
    assert _visible_braces(structural) == ""
    assert structural.endswith(";" + " " * (len(trailing) + 1) + "\nz = 1;")


def test_scan_handles_extreme_template_nesting_without_recursing() -> None:
    """Nesting depth is bounded by memory, not by the interpreter's recursion limit."""
    depth = 5000
    content = "`${" * depth + "x" + "}`" * depth + ";\ny = 1;"

    scan, structural = _scan_typescript(content)

    assert scan == content
    assert structural == chr(0) * (len(content) - len(";\ny = 1;")) + ";\ny = 1;"


@pytest.mark.parametrize(
    "content",
    [
        "x: `a${`b${c}//d`}//e`;",
        'x: `${`${"`"}`}//kept`;',
        "x: `${`a\\`//b`}/* c */`;",
        "x: `${`${`//deep`}//mid`}//outer`;",
        "x: `${ {a: `//obj`}.a }//kept`;",
    ],
)
def test_strip_typescript_comments_leaves_nested_template_text_alone(content: str) -> None:
    """Comment markers in nested template text survive, however deeply they are nested."""
    assert strip_typescript_comments(content) == content


def test_strip_typescript_comments_blanks_comments_in_nested_expression_code() -> None:
    """Comments in expression code at any depth are blanked; template text around them is kept."""
    first, second, third = "/* c1 */", "/* c2 */", "// c3"
    content = f"x: `${{{first} `//in${{{second} y}}` }}// kept`; {third}"

    assert strip_typescript_comments(content) == (
        f"x: `${{{_blank(first)} `//in${{{_blank(second)} y}}` }}// kept`; {_blank(third)}"
    )


@pytest.mark.parametrize(
    ("code", "comment"),
    [
        ("const half = total / 2; ", "// it's half"),
        ("const mean = (a + b) / 2 / c; ", "// it's"),
        ("const q = items[0] / items[1]; ", "// don't"),
        ("const t = `${a / b}// text`; ", "// it's"),
    ],
)
def test_strip_typescript_comments_treats_slash_after_an_operand_as_division(
    code: str, comment: str
) -> None:
    """A `/` after a value is division, so a quote in the following comment stays a comment."""
    assert strip_typescript_comments(code + comment) == code + _blank(comment)


@pytest.mark.parametrize(
    "code",
    [
        "x = /'/g; ",
        'f(/"/, 1); ',
        "const o = { re: /'/ }; ",
        "function f(s) { return /'/.test(s); } ",
        "x = /[/']/; ",
        "x = /\\/'/; ",
        "x = a ? /'/ : /\"/; ",
    ],
)
def test_strip_typescript_comments_treats_slash_in_expression_position_as_a_regex(
    code: str,
) -> None:
    """A `/` where a value may start opens a regex, so its quote does not hide the comment."""
    comment = "// tail 'quote"

    assert strip_typescript_comments(code + comment) == code + _blank(comment)


@pytest.mark.parametrize(
    "code",
    ["const t = s => /'/.test(s); ", "const t = 'a' + /'/.source; "],
)
def test_regex_heuristic_misses_a_regex_after_an_arrow_or_arithmetic_operator(code: str) -> None:
    """Documented limitation: the heuristic reads `/` after `>` or `+` as division.

    The regex's quote then opens a string that ends at the line break and hides the comment after
    it. The heuristic is shared by comment stripping and literal masking and is unchanged here.
    """
    content = code + "// tail 'quote"

    assert strip_typescript_comments(content) == content


def test_parse_ignores_braces_inside_regex_literals_but_not_after_division() -> None:
    """Regex braces are masked; a division does not swallow the rest of its line."""
    content = """const open = /{+/g;
const close = /}+/u;
const ratio = total / count; const box = { a: 1 };
interface After { b: string }
"""
    result = TypeScriptParser().parse(relative_path="re.ts", content=content)

    assert [i.name for i in result.interfaces] == ["After"]
    _, structural = _scan_typescript(content)
    assert _visible_braces(structural) == "{}{}"


def test_parse_handles_regex_and_division_inside_template_expressions() -> None:
    """Slashes in `${...}` are classified like slashes anywhere else."""
    content = """const a = `${total / count}{`;
const b = `${/}/.test(s)}{`;
interface After { c: string }
"""
    result = TypeScriptParser().parse(relative_path="t.ts", content=content)

    assert [i.name for i in result.interfaces] == ["After"]


def test_jsx_text_apostrophe_only_affects_its_own_line() -> None:
    """JSX is not parsed: an apostrophe in JSX text starts a string that ends at its line break.

    The damage is bounded by that line; comments and declarations after it are unaffected.
    """
    content = """const el = <p>Don't panic</p>;
// real comment: interface Hidden { a: string }
interface After { a: string }
"""
    result = TypeScriptParser().parse(relative_path="view.tsx", content=content)

    assert [i.name for i in result.interfaces] == ["After"]
    assert "Hidden" not in strip_typescript_comments(content)


def test_jsx_text_apostrophe_hides_a_comment_marker_on_the_same_line() -> None:
    """Documented limitation: JSX text is not recognized, so the apostrophe opens a string."""
    content = "const el = <p>Don't // not stripped</p>;\n"

    assert strip_typescript_comments(content) == content


# --- class bodies: braces in literals must not move class or method boundaries -----------

_HIDDEN_BRACE_STATEMENTS = [
    pytest.param('return "{";', id="double-quoted-open"),
    pytest.param('return "}";', id="double-quoted-close"),
    pytest.param("return '{';", id="single-quoted-open"),
    pytest.param("return '}';", id="single-quoted-close"),
    pytest.param("return `{`;", id="template-text-open"),
    pytest.param("return `}`;", id="template-text-close"),
    pytest.param("return `a${ {b: 1}.b }{`;", id="template-expression-braces"),
    pytest.param("return `${`{`}`;", id="nested-template-open"),
    pytest.param("return `${`}`}`;", id="nested-template-close"),
    pytest.param("return /{/.source;", id="regex-open"),
    pytest.param("return /}/.source;", id="regex-close"),
    pytest.param("return /[{]/.source;", id="regex-class"),
    pytest.param('return "{{" + \'}\' + /}/.source;', id="mixed"),
]


@pytest.mark.parametrize("statement", _HIDDEN_BRACE_STATEMENTS)
def test_parse_class_methods_survive_a_hidden_brace_in_an_earlier_method_body(
    statement: str,
) -> None:
    """A brace inside a string, template, or regex never moves the class or method boundaries."""
    content = f"""class A {{
    m(): string {{ {statement} }}
    n(): void {{}}
    o(value: number): number {{ return value; }}
}}
function free(): void {{}}
interface After {{ a: string }}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [c.name for c in result.classes] == ["A"]
    methods = result.classes[0].methods
    assert [(m.name, m.return_type, m.line_number) for m in methods] == [
        ("m", "string", 2),
        ("n", "void", 3),
        ("o", "number", 4),
    ]
    assert [f.name for f in result.functions] == ["free"]
    assert [i.name for i in result.interfaces] == ["After"]


def test_parse_the_documented_class_example_extracts_both_methods() -> None:
    """The motivating example: `m` returns a string containing `{`, and `n` must still be found."""
    content = """class A {
  m() { return "{"; }
  n() {}
}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [(m.name, m.line_number) for m in result.classes[0].methods] == [("m", 2), ("n", 3)]


def test_parse_free_function_after_a_class_is_not_swallowed_by_a_hidden_brace() -> None:
    """The class body span ends at the class's real closing brace, so later code stays outside."""
    content = """class A {
    m() { return "{"; }
}
function free() {}
const arrow = (value: number) => value;
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [m.name for m in result.classes[0].methods] == ["m"]
    assert [f.name for f in result.functions] == ["free", "arrow"]


def test_parse_classes_after_a_class_with_hidden_braces_are_all_found() -> None:
    """Later classes keep their own names, bases, methods, doc comments, and line numbers."""
    content = """class A {
    m() { return "}"; }
}

/** Documented. */
export class B extends A {
    n(): void {}
    o() { return `${`{`}`; }
}
abstract class C implements Runnable {
    p(): number { return 1; }
}
function tail(): void {}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [(c.name, c.base_classes, c.line_number) for c in result.classes] == [
        ("A", (), 1),
        ("B", ("A",), 6),
        ("C", ("Runnable",), 10),
    ]
    assert [[m.name for m in c.methods] for c in result.classes] == [["m"], ["n", "o"], ["p"]]
    assert [f.name for f in result.functions] == ["tail"]
    assert result.classes[1].docstring is not None
    assert "Documented." in result.classes[1].docstring


def test_parse_nested_class_declarations_stay_out_and_do_not_disturb_the_outer_class() -> None:
    """A class declared inside a method body is not file-scope; its methods are not the outer's."""
    content = """class Outer {
    m() {
        const text = "{";
        class Inner {
            z() { return "}"; }
        }
        return text;
    }
    n() {}
}
class After {
    q() {}
}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [c.name for c in result.classes] == ["Outer", "After"]
    assert [m.name for m in result.classes[0].methods] == ["m", "n"]
    assert [m.name for m in result.classes[1].methods] == ["q"]


def test_parse_class_boundaries_still_follow_real_code_braces() -> None:
    """Real blocks, object literals, and nested functions still open and close bodies correctly."""
    content = """class A {
    m(flag: boolean): object {
        if (flag) {
            return { key: "}", other: { deep: `{` } };
        } else {
            helper(1);
        }
        const callback = () => { call("x"); };
        return {};
    }
    n(): void {}
}
class B {
    o() {}
}
function after() {}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [[m.name for m in c.methods] for c in result.classes] == [["m", "n"], ["o"]]
    assert [(m.name, m.line_number) for m in result.classes[0].methods] == [("m", 2), ("n", 11)]
    assert [f.name for f in result.functions] == ["after"]


def test_parse_class_member_text_and_line_numbers_come_from_the_original_source() -> None:
    """Names, parameters, return types, and lines are read from the original text, not the mask."""
    content = """/**
 * The widget.
 */
export class Widget extends Base {
    // a comment with a brace }
    async load(id: string, options?: Array<string>): Promise<T> {
        return fetch(`/items/${id}{`);
    }
    static create<U>(value: U): Widget<U> { return new Widget("}"); }
}
"""
    result = TypeScriptParser().parse(relative_path="widget.ts", content=content)

    widget = result.classes[0]
    assert (widget.name, widget.base_classes, widget.line_number) == ("Widget", ("Base",), 4)
    assert widget.docstring is not None
    assert "The widget." in widget.docstring
    assert [
        (m.name, m.parameters, m.return_type, m.is_async, m.line_number) for m in widget.methods
    ] == [
        ("load", ("id: string", "options?: Array<string>"), "Promise<T>", True, 6),
        ("create", ("value: U",), "Widget<U>", False, 9),
    ]


# --- class bodies: text inside literals must not be read as a method declaration ---------

_METHOD_LOOKALIKE_PROPERTIES = [
    pytest.param('x = "foo(bar)";', id="double-quoted"),
    pytest.param("x = 'foo(bar)';", id="single-quoted"),
    pytest.param("x = `foo(bar)`;", id="template"),
    pytest.param("x = `a${b}foo(bar)`;", id="template-with-expression"),
    pytest.param("x = `a${`foo(bar)`}b`;", id="nested-template"),
    pytest.param("x = `foo(bar)${`inner`}`;", id="template-text-around-nested-template"),
    pytest.param("x = /foo(bar)/g;", id="regex"),
    pytest.param("static re = /\\bfoo\\(bar\\)/;", id="regex-with-escapes"),
    pytest.param('x = "say \\"foo(bar)\\"";', id="escaped-quotes"),
    pytest.param("x = [\"foo(a)\", 'foo(b)', `foo(c)`, /foo(d)/];", id="every-literal-kind"),
    pytest.param('x = "async get foo(bar)";', id="modifier-lookalike"),
]


def test_parse_class_extracts_only_the_real_method_next_to_a_call_like_string() -> None:
    """The motivating example: `"foo(bar)"` is a string value, so only `m` is a method."""
    content = 'class A {\n  x = "foo(bar)";\n  m() {}\n}\n'

    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [(m.name, m.parameters, m.return_type, m.line_number) for m in result.classes[0].methods] == [
        ("m", (), None, 3)
    ]


@pytest.mark.parametrize("prop", _METHOD_LOOKALIKE_PROPERTIES)
def test_parse_class_ignores_method_lookalikes_inside_property_literals(prop: str) -> None:
    """A valid method before and after a property whose literal reads like a method call."""
    content = f"""class A {{
    before(): string {{ return "b"; }}
    {prop}
    after(value: number): number {{ return value; }}
}}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [(m.name, m.return_type, m.line_number) for m in result.classes[0].methods] == [
        ("before", "string", 2),
        ("after", "number", 4),
    ]


def test_parse_class_ignores_every_lookalike_literal_between_valid_methods() -> None:
    """Several lookalike properties in a row never add a method or move a real one."""
    content = """class A {
    before(): string { return "b"; }
    x = "foo(bar)";
    y = 'foo(bar)';
    z = `foo(bar)`;
    n = `a${`foo(bar)`}b`;
    r = /foo(bar)/g;
    middle(): void {}
    s = "baz(qux)";
    after(value: number): number { return value; }
}
function free(): void {}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [(m.name, m.return_type, m.line_number) for m in result.classes[0].methods] == [
        ("before", "string", 2),
        ("middle", "void", 8),
        ("after", "number", 10),
    ]
    assert [f.name for f in result.functions] == ["free"]


def test_parse_class_keeps_the_original_parameter_text_of_a_call_like_default_string() -> None:
    """Metadata is read from the original text: the string default is kept verbatim."""
    content = """class A {
    async load(path: string = "v(1)", flag = 'w(2)'): Promise<void> {}
    n(): void {}
}
"""
    result = TypeScriptParser().parse(relative_path="a.ts", content=content)

    assert [
        (m.name, m.parameters, m.return_type, m.is_async, m.line_number)
        for m in result.classes[0].methods
    ] == [
        ("load", ('path: string = "v(1)"', "flag = 'w(2)'"), "Promise<void>", True, 2),
        ("n", (), "void", False, 3),
    ]


def test_parse_class_valid_method_declarations_are_unchanged() -> None:
    """Regression: constructors, modifiers, accessors, generators, and optional methods."""
    content = """export abstract class Shape {
    constructor(private readonly id: string) {}
    public static async load<T>(id: string): Promise<T> { return null as T; }
    get size(): number { return 1; }
    set size(value: number) {}
    private helper(): void {}
    protected abstract area(): number;
    *gen(): Generator<number> { yield 1; }
    render?(): void;
    async tick() {}
}
"""
    result = TypeScriptParser().parse(relative_path="shape.ts", content=content)

    assert [
        (m.name, m.parameters, m.return_type, m.is_async, m.line_number)
        for m in result.classes[0].methods
    ] == [
        ("constructor", ("private readonly id: string",), None, False, 2),
        ("load", ("id: string",), "Promise<T>", True, 3),
        ("size", (), "number", False, 4),
        ("size", ("value: number",), None, False, 5),
        ("helper", (), "void", False, 6),
        ("area", (), "number", False, 7),
        ("gen", (), "Generator<number>", False, 8),
        ("render", (), "void", False, 9),
        ("tick", (), None, True, 10),
    ]


def test_scan_keeps_both_scans_aligned_for_a_class_with_lookalike_literals() -> None:
    """The scan used to find methods and the one used to read them have identical offsets."""
    content = 'class A {\n  x = `a${`foo(bar)`}b`;\n  m() { return /foo(bar)/; }\n}\n'

    scan, structural = _scan_typescript(content)

    assert len(scan) == len(structural) == len(content)
    assert "foo(bar)" in scan
    assert "foo(bar)" not in structural


# --- interface bodies: text inside literals must not be read as a method declaration -----


def _interface_method_view(content: str) -> list[tuple[str, tuple[str, ...], str | None, int]]:
    """Parse `content` and return `(name, parameters, return_type, line)` for interface methods."""
    result = TypeScriptParser().parse(relative_path="ports.ts", content=content)
    return [
        (m.name, m.parameters, m.return_type, m.line_number) for m in result.interfaces[0].methods
    ]


def test_parse_interface_extracts_only_the_real_methods_next_to_a_call_like_string() -> None:
    """The motivating example: `"a(b)"` is a literal type, so `a` is not a method."""
    content = 'interface A {\n  find(kind: "a(b)"): Result;\n  run(): void;\n}\n'

    assert _interface_method_view(content) == [
        ("find", ('kind: "a(b)"',), "Result", 2),
        ("run", (), "void", 3),
    ]


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        pytest.param(
            'find(kind: "a(b)"): Result;',
            ("find", ('kind: "a(b)"',), "Result", 3),
            id="double-quoted-parameter-type",
        ),
        pytest.param(
            "find(kind: 'a(b)'): Result;",
            ("find", ("kind: 'a(b)'",), "Result", 3),
            id="single-quoted-parameter-type",
        ),
        pytest.param(
            'find(kind: "a(b)", other?: \'c(d)\'): Result;',
            ("find", ('kind: "a(b)"', "other?: 'c(d)'"), "Result", 3),
            id="two-literal-parameters",
        ),
        pytest.param(
            "find(kind: `a(${string})`): Result;",
            ("find", ("kind: `a(${string})`",), "Result", 3),
            id="template-parameter-type",
        ),
        pytest.param(
            "find(kind: `a(${`b(c)`})`): Result;",
            ("find", ("kind: `a(${`b(c)`})`",), "Result", 3),
            id="nested-template-parameter-type",
        ),
        pytest.param(
            "find(kind: /a(b)/g): Result;",
            ("find", ("kind: /a(b)/g",), "Result", 3),
            id="regex-literal-in-parameter-list",
        ),
        pytest.param(
            'find?(kind: "a(b)"): Result;',
            ("find", ('kind: "a(b)"',), "Result", 3),
            id="optional-method",
        ),
        pytest.param(
            'map<U extends "x(y)">(value: U): U;',
            ("map", ("value: U",), "U", 3),
            id="generic-method-with-literal-constraint",
        ),
        pytest.param(
            "map<U>(value: U, kind: 'k(l)'): Array<U>;",
            ("map", ("value: U", "kind: 'k(l)'"), "Array<U>", 3),
            id="generic-method-with-literal-parameter",
        ),
    ],
)
def test_parse_interface_method_with_a_lookalike_literal_is_the_only_method_found(
    member: str, expected: tuple[str, tuple[str, ...], str | None, int]
) -> None:
    """The literal inside a real method signature adds no method; the real ones keep their text."""
    content = f"""interface A {{
    before(): string;
    {member}
    after(value: number): number;
}}
"""
    assert _interface_method_view(content) == [
        ("before", (), "string", 2),
        expected,
        ("after", ("value: number",), "number", 4),
    ]


@pytest.mark.parametrize(
    ("member", "name", "type_annotation"),
    [
        pytest.param('kind: "a(b)";', "kind", '"a(b)"', id="double-quoted"),
        pytest.param("kind: 'a(b)';", "kind", "'a(b)'", id="single-quoted"),
        pytest.param("kind: `a(${string})`;", "kind", "`a(${string})`", id="template"),
        pytest.param("kind: `a(${`b(c)`})`;", "kind", "`a(${`b(c)`})`", id="nested-template"),
        pytest.param("kind: /a(b)/g;", "kind", "/a(b)/g", id="regex-literal"),
        pytest.param(
            'handler: (value: "x(y)") => void;',
            "handler",
            '(value: "x(y)") => void',
            id="function-type",
        ),
        pytest.param(
            'meta: { run(): void; tag: "z(w)" };',
            "meta",
            '{ run(): void; tag: "z(w)" }',
            id="object-type",
        ),
        pytest.param(
            'factory: new (name: "n(m)") => A;',
            "factory",
            'new (name: "n(m)") => A',
            id="construct-type",
        ),
    ],
)
def test_parse_interface_property_with_a_lookalike_literal_is_not_a_method(
    member: str, name: str, type_annotation: str
) -> None:
    """A property is a property: neither it nor its type's text adds a method."""
    content = f"""interface A {{
    before(): string;
    {member}
    after(value: number): number;
}}
"""
    result = TypeScriptParser().parse(relative_path="ports.ts", content=content)

    interface = result.interfaces[0]
    assert [(m.name, m.return_type, m.line_number) for m in interface.methods] == [
        ("before", "string", 2),
        ("after", "number", 4),
    ]
    assert [(p.name, p.type_annotation, p.line_number) for p in interface.properties] == [
        (name, type_annotation, 3)
    ]


def test_parse_interface_with_every_lookalike_keeps_exact_methods_and_properties() -> None:
    """Methods and properties interleaved with lookalike literals are each reported once, exactly."""
    content = """interface Mixed {
    first(): string;
    kind: "a(b)";
    find(kind: 'c(d)', fallback?: `e(${string})`): Result;
    pattern: /f(g)/g;
    handler: (value: "x(y)") => void;
    map<U extends "p(q)">(value: U): U;
    meta: { run(): void; tag: "z(w)" };
    tryFind?(kind: "h(i)"): Result;
    last(value: number): number;
}
"""
    result = TypeScriptParser().parse(relative_path="mixed.ts", content=content)

    interface = result.interfaces[0]
    assert [(m.name, m.parameters, m.return_type, m.line_number) for m in interface.methods] == [
        ("first", (), "string", 2),
        ("find", ("kind: 'c(d)'", "fallback?: `e(${string})`"), "Result", 4),
        ("map", ("value: U",), "U", 7),
        ("tryFind", ('kind: "h(i)"',), "Result", 9),
        ("last", ("value: number",), "number", 10),
    ]
    assert [(p.name, p.line_number) for p in interface.properties] == [
        ("kind", 3),
        ("pattern", 5),
        ("handler", 6),
        ("meta", 8),
    ]


def test_parse_interface_valid_method_signatures_are_unchanged() -> None:
    """Regression: optional, generic, accessor, and plain signatures parse exactly as before."""
    content = """interface Repository<T> extends Base<T> {
    find(id: string): Promise<T>;
    save?(value: T): void;
    map<U extends Record<string, Array<T>>>(value: U): Promise<Array<U>>;
    get size(): number;
    set size(value: number);
}
"""
    assert _interface_method_view(content) == [
        ("find", ("id: string",), "Promise<T>", 2),
        ("save", ("value: T",), "void", 3),
        ("map", ("value: U",), "Promise<Array<U>>", 4),
        ("size", (), "number", 5),
        ("size", ("value: number",), None, 6),
    ]


def test_scan_keeps_both_scans_aligned_for_an_interface_with_lookalike_literals() -> None:
    """The scan used to find interface methods and the one used to read them align exactly."""
    content = 'interface A {\n  find(kind: `a(${`b(c)`})`): R;\n  k: "d(e)";\n}\n'

    scan, structural = _scan_typescript(content)

    assert len(scan) == len(structural) == len(content)
    assert "a(" in scan
    assert "a(" not in structural
    assert "d(e)" not in structural


# --- method signatures: parameters and return types with literals and generics -----------

_SignatureView = tuple[str, tuple[str, ...], str | None, int]


def _class_signatures(content: str) -> list[_SignatureView]:
    """Parse `content` and return `(name, parameters, return_type, line)` of the first class."""
    result = TypeScriptParser().parse(relative_path="sig.ts", content=content)
    return [
        (m.name, m.parameters, m.return_type, m.line_number) for m in result.classes[0].methods
    ]


def test_parse_interface_method_with_a_paren_inside_a_string_parameter_type() -> None:
    """A `)` inside a literal type does not close the parameter list early."""
    content = 'interface A {\n  find(kind: "a)b"): Result;\n  run(): void;\n}\n'

    assert _interface_method_view(content) == [
        ("find", ('kind: "a)b"',), "Result", 2),
        ("run", (), "void", 3),
    ]


def test_parse_interface_method_with_braces_in_a_string_return_type() -> None:
    """A `{` or `}` inside a literal return type does not end the return type early."""
    content = 'interface A {\n  find(): "{" | "}";\n  run(): void;\n}\n'

    assert _interface_method_view(content) == [
        ("find", (), '"{" | "}"', 2),
        ("run", (), "void", 3),
    ]


def test_parse_interface_method_with_a_comma_inside_generic_arguments() -> None:
    """`Map<string, number>` is one parameter, not two."""
    content = (
        "interface A {\n"
        "  load(value: Map<string, number>, key: string): Result;\n"
        "  run(): void;\n"
        "}\n"
    )
    assert _interface_method_view(content) == [
        ("load", ("value: Map<string, number>", "key: string"), "Result", 2),
        ("run", (), "void", 3),
    ]


def test_parse_class_method_with_a_paren_inside_a_string_parameter_type() -> None:
    """The same holds for class methods, whose body follows the signature."""
    content = 'class A {\n  find(kind: "a)b"): Result { return "(" ; }\n  run(): void {}\n}\n'

    assert _class_signatures(content) == [
        ("find", ('kind: "a)b"',), "Result", 2),
        ("run", (), "void", 3),
    ]


def test_parse_class_method_with_braces_in_a_string_return_type() -> None:
    """The body's `{` is found after a return type whose literals contain braces."""
    content = 'class A {\n  find(): "{" | "}" { return "}"; }\n  run(): void {}\n}\n'

    assert _class_signatures(content) == [
        ("find", (), '"{" | "}"', 2),
        ("run", (), "void", 3),
    ]


def test_parse_class_method_with_a_comma_inside_generic_arguments() -> None:
    """`Map<string, number>` is one parameter in a class method too."""
    content = (
        "class A {\n"
        "  load(value: Map<string, number>, key: string): Result { return null; }\n"
        "  run(): void {}\n"
        "}\n"
    )
    assert _class_signatures(content) == [
        ("load", ("value: Map<string, number>", "key: string"), "Result", 2),
        ("run", (), "void", 3),
    ]


_COMBINED_SIGNATURES: list[_SignatureView] = [
    ("find", ('kind: "a)b"',), "Result", 2),
    ("kinds", (), '"{" | "}"', 3),
    ("load", ("value: Map<string, number>", "key: string"), "Result", 4),
    ("last", (), "void", 5),
]


def test_parse_interface_combines_literal_parens_literal_braces_and_generic_commas() -> None:
    """All three cases together in one interface, with exact signatures and lines."""
    content = """interface Repo {
    find(kind: "a)b"): Result;
    kinds(): "{" | "}";
    load(value: Map<string, number>, key: string): Result;
    last(): void;
}
"""
    assert _interface_method_view(content) == _COMBINED_SIGNATURES


def test_parse_class_combines_literal_parens_literal_braces_and_generic_commas() -> None:
    """All three cases together in one class, with exact signatures and lines."""
    content = """class Repo {
    find(kind: "a)b"): Result { return "}"; }
    kinds(): "{" | "}" { return "{"; }
    load(value: Map<string, number>, key: string): Result { return null; }
    last(): void {}
}
"""
    assert _class_signatures(content) == _COMBINED_SIGNATURES


@pytest.mark.parametrize(
    ("signature", "expected_parameters", "expected_return"),
    [
        pytest.param("m(a: 'x)y'): R", ("a: 'x)y'",), "R", id="single-quoted-close-paren"),
        pytest.param('m(a: "x(y"): R', ('a: "x(y"',), "R", id="double-quoted-open-paren"),
        pytest.param('m(a: "x,y", b: number): R', ('a: "x,y"', "b: number"), "R", id="comma"),
        pytest.param('m(a: "x{y", b: "}"): R', ('a: "x{y"', 'b: "}"'), "R", id="braces"),
        pytest.param("m(a: `x)${string}`): R", ("a: `x)${string}`",), "R", id="template"),
        pytest.param(
            "m(a: `x)${`y)`}`, b: number): R",
            ("a: `x)${`y)`}`", "b: number"),
            "R",
            id="nested-template",
        ),
        pytest.param(
            "m(v: Map<string, Array<Record<string, number>>>, k: string): R",
            ("v: Map<string, Array<Record<string, number>>>", "k: string"),
            "R",
            id="nested-generics",
        ),
        pytest.param(
            "m(h: Array<(x: number, y: number) => void>, k: string): R",
            ("h: Array<(x: number, y: number) => void>", "k: string"),
            "R",
            id="arrow-in-generic-argument",
        ),
        pytest.param(
            "m(cb: <T, U>(a: T) => U, other: string): R",
            ("cb: <T, U>(a: T) => U", "other: string"),
            "R",
            id="generic-function-type",
        ),
        pytest.param(
            "m(a = 1 < 2, b: number): R",
            ("a = 1 < 2", "b: number"),
            "R",
            id="comparison-in-default-value",
        ),
        pytest.param(
            "m(a: number, b: string = 'x'): Promise<Map<string, number>>",
            ("a: number", "b: string = 'x'"),
            "Promise<Map<string, number>>",
            id="generic-return-type",
        ),
    ],
)
def test_parse_method_signature_edge_cases_in_an_interface_and_a_class(
    signature: str, expected_parameters: tuple[str, ...], expected_return: str
) -> None:
    """Literals and generics in parameters never change where a parameter starts or ends."""
    expected = [("m", expected_parameters, expected_return, 2), ("n", (), "void", 3)]

    interface = f"interface A {{\n  {signature};\n  n(): void;\n}}\n"
    klass = f"class A {{\n  {signature} {{}}\n  n(): void {{}}\n}}\n"

    assert _interface_method_view(interface) == expected
    assert _class_signatures(klass) == expected


def test_parse_method_parameters_keep_their_original_multiline_text() -> None:
    """Parameter text is the original slice: line breaks and indentation inside it stay."""
    content = """interface A {
    load(
        value: Map<
            string,
            number
        >,
        key: string,
    ): Result;
}
"""
    assert _interface_method_view(content) == [
        (
            "load",
            ("value: Map<\n            string,\n            number\n        >", "key: string"),
            "Result",
            2,
        )
    ]


def test_parse_method_signatures_for_every_modifier_are_unchanged() -> None:
    """Regression: plain, generic, optional, async, getter, and setter methods parse as before."""
    content = """class Service {
    plain(id: string): number { return 1; }
    generic<T extends object>(value: T, items: Array<T>): Promise<T> { return value; }
    async fetch(url: string, retries?: number): Promise<void> {}
    get size(): number { return 1; }
    set size(value: number) {}
    static create(): Service { return new Service(); }
}
interface Port {
    plain(id: string): number;
    optional?(value: string): void;
    generic<T>(value: T): T;
    get size(): number;
    set size(value: number);
}
"""
    result = TypeScriptParser().parse(relative_path="sig.ts", content=content)

    assert [
        (m.name, m.parameters, m.return_type, m.is_async, m.line_number)
        for m in result.classes[0].methods
    ] == [
        ("plain", ("id: string",), "number", False, 2),
        ("generic", ("value: T", "items: Array<T>"), "Promise<T>", False, 3),
        ("fetch", ("url: string", "retries?: number"), "Promise<void>", True, 4),
        ("size", (), "number", False, 5),
        ("size", ("value: number",), None, False, 6),
        ("create", (), "Service", False, 7),
    ]
    assert [
        (m.name, m.parameters, m.return_type, m.line_number) for m in result.interfaces[0].methods
    ] == [
        ("plain", ("id: string",), "number", 10),
        ("optional", ("value: string",), "void", 11),
        ("generic", ("value: T",), "T", 12),
        ("size", (), "number", 13),
        ("size", ("value: number",), None, 14),
    ]


# --- free functions and arrow functions: the same literal- and generic-aware signatures ---

_FunctionView = tuple[str, tuple[str, ...], str | None, bool, int]


def _function_view(content: str) -> list[_FunctionView]:
    """Parse `content` and return `(name, parameters, return_type, is_async, line)` per function."""
    result = TypeScriptParser().parse(relative_path="fn.ts", content=content)
    return [
        (f.name, f.parameters, f.return_type, f.is_async, f.line_number) for f in result.functions
    ]


def test_parse_function_with_a_paren_inside_a_string_parameter_type() -> None:
    """A `)` inside a literal type does not close the parameter list of a named function."""
    content = 'function find(kind: "a)b"): Result {}\nfunction run(): void {}\n'

    assert _function_view(content) == [
        ("find", ('kind: "a)b"',), "Result", False, 1),
        ("run", (), "void", False, 2),
    ]


def test_parse_function_with_generic_commas_and_multiline_parameters() -> None:
    """`Map<string, number>` is one parameter, and the original multi-line text is preserved."""
    content = """function load(
    value: Map<string, number>,
    key: string
): Result {}
"""
    assert _function_view(content) == [
        ("load", ("value: Map<string, number>", "key: string"), "Result", False, 1)
    ]


def test_parse_function_with_braces_in_a_string_return_type() -> None:
    """A `{` or `}` inside a literal return type does not end it; the body `{` still does."""
    content = 'function getKind(): "{" | "}" {}\nfunction after(): void {}\n'

    assert _function_view(content) == [
        ("getKind", (), '"{" | "}"', False, 1),
        ("after", (), "void", False, 2),
    ]


def test_parse_arrow_function_with_a_paren_inside_a_string_parameter_type() -> None:
    """The documented async arrow example: the `)` in the literal type is not the list's end."""
    content = 'const findAsync = async (\n    kind: "a)b"\n): Promise<Result> => {}\n'

    assert _function_view(content) == [
        ("findAsync", ('kind: "a)b"',), "Promise<Result>", True, 1)
    ]


def test_parse_generic_arrow_function_with_multiline_parameters() -> None:
    """The documented generic arrow example is recognized, with its parameters intact."""
    content = """const load = <T>(
    value: Map<string, T>,
    key: string
): Result => value
"""
    assert _function_view(content) == [
        ("load", ("value: Map<string, T>", "key: string"), "Result", False, 1)
    ]


def test_parse_generic_arrow_function_is_a_function_symbol_and_not_a_constant() -> None:
    """A generic arrow is reported as a function and excluded from the constants, like any arrow."""
    content = "export const load = async <T, U>(a: T, b: Map<string, U>): Promise<void> => {};\n"

    result = TypeScriptParser().parse(relative_path="fn.ts", content=content)

    assert _function_view(content) == [
        ("load", ("a: T", "b: Map<string, U>"), "Promise<void>", True, 1)
    ]
    assert [s.kind for s in result.symbols if s.name == "load"] == [SymbolKind.FUNCTION]


def test_parse_function_with_a_paren_inside_its_type_parameters() -> None:
    """A `(` in a type-parameter constraint is not the parameter list's opening paren."""
    content = "function f<T extends (x: number) => void>(a: T, b: Map<string, T>): void {}\n"

    assert _function_view(content) == [("f", ("a: T", "b: Map<string, T>"), "void", False, 1)]


@pytest.mark.parametrize(
    ("parameters", "expected_parameters"),
    [
        pytest.param("a: 'x)y'", ("a: 'x)y'",), id="single-quoted-close-paren"),
        pytest.param('a: "x(y"', ('a: "x(y"',), id="double-quoted-open-paren"),
        pytest.param('a: "x,y", b: number', ('a: "x,y"', "b: number"), id="comma-in-string"),
        pytest.param('a: "x{y", b: "}"', ('a: "x{y"', 'b: "}"'), id="braces-in-strings"),
        pytest.param("a: `x)${string}`", ("a: `x)${string}`",), id="template"),
        pytest.param(
            "a: `x)${`y)`}`, b: number",
            ("a: `x)${`y)`}`", "b: number"),
            id="nested-template",
        ),
        pytest.param(
            "v: Map<string, Array<Record<string, number>>>, k: string",
            ("v: Map<string, Array<Record<string, number>>>", "k: string"),
            id="nested-generics",
        ),
        pytest.param(
            "h: Array<(x: number, y: number) => void>, k: string",
            ("h: Array<(x: number, y: number) => void>", "k: string"),
            id="arrow-type-in-generic-argument",
        ),
        pytest.param(
            "cb: <T, U>(a: T) => U, other: string",
            ("cb: <T, U>(a: T) => U", "other: string"),
            id="generic-function-type",
        ),
        pytest.param(
            "a?: number, b = 'x', ...rest: string[]",
            ("a?: number", "b = 'x'", "...rest: string[]"),
            id="optional-default-and-rest",
        ),
        pytest.param(
            "pattern = /\\)/g, k: string",
            ("pattern = /\\)/g", "k: string"),
            id="regex-default",
        ),
        pytest.param("a = 1 < 2, b: number", ("a = 1 < 2", "b: number"), id="comparison-default"),
        pytest.param("", (), id="no-parameters"),
    ],
)
def test_parse_function_and_arrow_parameter_edge_cases(
    parameters: str, expected_parameters: tuple[str, ...]
) -> None:
    """Named functions and arrow functions read the same parameters from the same text."""
    named = f"function m({parameters}): R {{}}\n"
    arrow = f"const m = ({parameters}): R => {{}}\n"
    asynchronous = f"const m = async ({parameters}): R => {{}}\n"

    assert _function_view(named) == [("m", expected_parameters, "R", False, 1)]
    assert _function_view(arrow) == [("m", expected_parameters, "R", False, 1)]
    assert _function_view(asynchronous) == [("m", expected_parameters, "R", True, 1)]


@pytest.mark.parametrize(
    "return_type",
    [
        pytest.param('"{" | "}"', id="braces"),
        pytest.param('"a;b"', id="semicolon"),
        pytest.param('"x=y" | "z"', id="equals"),
        pytest.param("`x}${string}`", id="template-with-brace"),
        pytest.param("`a${`b}`}`", id="nested-template"),
        pytest.param("Promise<Map<string, number>>", id="nested-generics"),
    ],
)
def test_parse_function_and_arrow_return_types_with_literals_and_generics(
    return_type: str,
) -> None:
    """Characters that would end a return type early stay inside it when they are in literals."""
    named = f"function m(): {return_type} {{ return null; }}\nfunction n(): void {{}}\n"
    arrow = f"const m = (): {return_type} => null;\nconst n = (): void => {{}};\n"

    assert _function_view(named) == [
        ("m", (), return_type, False, 1),
        ("n", (), "void", False, 2),
    ]
    assert _function_view(arrow) == [
        ("m", (), return_type, False, 1),
        ("n", (), "void", False, 2),
    ]


def test_parse_function_and_arrow_multiline_parameter_text_is_preserved_exactly() -> None:
    """Line breaks and indentation inside a parameter are kept, as for methods."""
    named = """function load(
    value: Map<
        string,
        number
    >,
    key: string,
): Result {}
"""
    arrow = """const load = (
    value: Map<
        string,
        number
    >,
    key: string,
): Result => value
"""
    expected = [
        (
            "load",
            ("value: Map<\n        string,\n        number\n    >", "key: string"),
            "Result",
            False,
            1,
        )
    ]
    assert _function_view(named) == expected
    assert _function_view(arrow) == expected


def test_parse_arrow_function_detection_ignores_literal_look_alikes() -> None:
    """`;` or `)` inside a literal type does not hide an arrow; a plain call is still no arrow."""
    content = """const a = (kind: "a)b"): "x;y" => kind;
const call = compute(1, 2);
const cast = <Foo>(value);
const b = (): void => {};
"""
    assert _function_view(content) == [
        ("a", ('kind: "a)b"',), '"x;y"', False, 1),
        ("b", (), "void", False, 4),
    ]


def test_parse_function_signatures_keep_line_numbers_and_docstrings() -> None:
    """Original line numbers and JSDoc comments are unaffected by the signature rewrite."""
    content = """/** Finds. */
export async function find(kind: "a)b"): Promise<Result> {}

/** Loads. */
export const load = <T>(value: Map<string, T>): T => value;
"""
    result = TypeScriptParser().parse(relative_path="fn.ts", content=content)

    assert [(f.name, f.line_number, f.docstring, f.is_async) for f in result.functions] == [
        ("find", 2, "Finds.", True),
        ("load", 5, "Loads.", False),
    ]


def test_parse_existing_function_signatures_are_unchanged() -> None:
    """Regression: the simple function and arrow shapes the parser always supported."""
    content = """export function add(a: number, b: number): number { return a + b; }
function greet(name: string) {}
export default function main(args: string[]): void {}
export async function go() {}
declare function ext(a: string): void;
const sq = (x: number): number => x * x;
const noop = () => {};
let typed: Handler = (z) => z;
const later = async (x) => x;
"""
    assert _function_view(content) == [
        ("add", ("a: number", "b: number"), "number", False, 1),
        ("greet", ("name: string",), None, False, 2),
        ("main", ("args: string[]",), "void", False, 3),
        ("go", (), None, True, 4),
        ("ext", ("a: string",), "void", False, 5),
        ("sq", ("x: number",), "number", False, 6),
        ("noop", (), None, False, 7),
        ("typed", ("z",), None, False, 8),
        ("later", ("x",), None, True, 9),
    ]


def test_parse_class_and_interface_method_signatures_are_unchanged_by_function_support() -> None:
    """Methods still read their signatures exactly as before, next to free functions."""
    content = """function free(a: "x)y"): void {}
class C {
    m(kind: "a)b"): "{" | "}" { return "{"; }
    load(value: Map<string, number>, key: string): Result { return null; }
}
interface I {
    m(kind: "a)b"): "{" | "}";
}
"""
    result = TypeScriptParser().parse(relative_path="mix.ts", content=content)

    assert [(f.name, f.parameters, f.return_type) for f in result.functions] == [
        ("free", ('a: "x)y"',), "void")
    ]
    assert [(m.name, m.parameters, m.return_type, m.line_number) for m in result.classes[0].methods] == [
        ("m", ('kind: "a)b"',), '"{" | "}"', 3),
        ("load", ("value: Map<string, number>", "key: string"), "Result", 4),
    ]
    assert [(m.name, m.parameters, m.return_type, m.line_number) for m in result.interfaces[0].methods] == [
        ("m", ('kind: "a)b"',), '"{" | "}"', 7)
    ]


# --- return types: object types, function types, and where an annotation really ends -----


def _return_types(content: str) -> list[tuple[str, str | None, int]]:
    """Parse `content`; `(name, return_type, line)` of every function and method found."""
    result = TypeScriptParser().parse(relative_path="rt.ts", content=content)
    items = [(f.name, f.return_type, f.line_number) for f in result.functions]
    for klass in result.classes:
        items += [(m.name, m.return_type, m.line_number) for m in klass.methods]
    for interface in result.interfaces:
        items += [(m.name, m.return_type, m.line_number) for m in interface.methods]
    return items


def _callable_forms(return_type: str) -> dict[str, tuple[str, int]]:
    """One source per callable kind declaring `m(): <return_type>` and then a plain `n(): void`.

    Maps the kind to `(source, line of m)`.
    """
    return {
        "function": (f"function m(): {return_type} {{ return null; }}\nfunction n(): void {{}}\n", 1),
        "arrow": (f"const m = (): {return_type} => null;\nconst n = (): void => {{}};\n", 1),
        "method": (
            f"class C {{\n  m(): {return_type} {{ return null; }}\n  n(): void {{}}\n}}\n",
            2,
        ),
        "interface": (f"interface I {{\n  m(): {return_type};\n  n(): void;\n}}\n", 2),
    }


_RETURN_TYPES = [
    pytest.param("{ a: string }", id="object"),
    pytest.param("{ a: string; b: { c: number; d: Array<string> } }", id="nested-properties"),
    pytest.param("{ a: { b: { c: string } } }", id="deeply-nested-object"),
    pytest.param("{ a: string, b?: number, readonly c: boolean }", id="comma-separated-object"),
    pytest.param("{ [key: string]: number }", id="index-signature-object"),
    pytest.param("{ run(): void; stop?(): void }", id="object-with-methods"),
    pytest.param("{}", id="empty-object"),
    pytest.param("() => void", id="function"),
    pytest.param("(x: number) => string", id="function-with-parameter"),
    pytest.param("(a: string, b: number) => boolean", id="function-with-parameters"),
    pytest.param("() => () => void", id="nested-function"),
    pytest.param("(a: string) => (b: number) => () => void", id="deeply-nested-function"),
    pytest.param("() => { a: string }", id="function-returning-object"),
    pytest.param("<T>(x: T) => T", id="generic-function"),
    pytest.param("(...rest: string[]) => void", id="function-with-rest"),
    pytest.param("({ a }: Props) => void", id="function-with-destructuring"),
    pytest.param("A | B", id="union"),
    pytest.param("A & B", id="intersection"),
    pytest.param("A | { x: 1 }", id="union-with-object"),
    pytest.param("{ a: 1 } | { b: 2 }", id="union-of-objects"),
    pytest.param("{ a: 1 } & Foo<Bar>", id="intersection-with-generic"),
    pytest.param("(() => void) | { a: 1 }", id="union-with-function-and-object"),
    pytest.param("(A | B)[]", id="parenthesized-union-array"),
    pytest.param("(A | B)", id="parenthesized-union"),
    pytest.param("Promise<{ a: string }>", id="generic-with-object"),
    pytest.param("Promise<() => void>", id="generic-with-function"),
    pytest.param("Map<string, { a: number }>", id="generic-with-comma-and-object"),
    pytest.param("Array<(x: number) => void>", id="generic-with-arrow"),
    pytest.param('"{" | "}"', id="literal-braces"),
    pytest.param('"a;b"', id="literal-semicolon"),
    pytest.param('"x=y" | "z"', id="literal-equals"),
    pytest.param("`x}${string}`", id="template-with-brace"),
    pytest.param('{ a: "}"; b: ";" }', id="object-with-literal-braces-and-semicolons"),
    pytest.param('() => "{"', id="function-returning-literal-brace"),
    pytest.param("T extends { a: 1 } ? X : Y", id="conditional-with-object"),
    pytest.param("typeof value", id="typeof"),
    pytest.param("keyof T", id="keyof"),
    pytest.param("T[number]", id="indexed-access"),
    pytest.param("string", id="plain"),
]


@pytest.mark.parametrize("return_type", _RETURN_TYPES)
@pytest.mark.parametrize("kind", ["function", "arrow", "method", "interface"])
def test_parse_return_type_boundaries_are_the_same_for_every_callable_kind(
    kind: str, return_type: str
) -> None:
    """Object and function types belong to the type; the body `{` and the arrow `=>` do not."""
    content, line = _callable_forms(return_type)[kind]

    assert _return_types(content) == [("m", return_type, line), ("n", "void", line + 1)]


@pytest.mark.parametrize("kind", ["function", "arrow"])
def test_parse_construct_type_return_for_functions_and_arrows(kind: str) -> None:
    """`new (...) => T` is a type here; interfaces and classes would read `new (` as a method."""
    content, line = _callable_forms("new (x: number) => Foo")[kind]

    assert _return_types(content) == [
        ("m", "new (x: number) => Foo", line),
        ("n", "void", line + 1),
    ]


def test_parse_the_documented_object_and_function_return_types() -> None:
    """The two confirmed defects, exactly as reported."""
    content = """function f(): { a: string } { return { a: "x" }; }
function g(): () => void {}
"""
    assert _return_types(content) == [("f", "{ a: string }", 1), ("g", "() => void", 2)]


MULTILINE_RETURN_TYPES = [
    pytest.param("{\n    a: string;\n    b: number;\n}", id="object"),
    pytest.param("{\n    a: {\n        b: string;\n    };\n}", id="nested-object"),
    pytest.param("| A\n    | B\n    | C", id="union-lines"),
    pytest.param("A\n    | B", id="union-continued-on-next-line"),
    pytest.param("(\n    a: string,\n    b: number\n) => void", id="function-parameters"),
    pytest.param("Map<\n    string,\n    number\n>", id="generic-arguments"),
    pytest.param("{ a: string } &\n    { b: number }", id="intersection-lines"),
]


@pytest.mark.parametrize("return_type", MULTILINE_RETURN_TYPES)
@pytest.mark.parametrize("kind", ["function", "arrow", "method", "interface"])
def test_parse_multiline_return_types_are_kept_whole(kind: str, return_type: str) -> None:
    """A return type spread over lines is one annotation, with its original text."""
    content, _ = _callable_forms(return_type)[kind]

    assert [(name, rt) for name, rt, _ in _return_types(content)] == [
        ("m", return_type),
        ("n", "void"),
    ]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("function m(): string{ return \"{\"; }", id="function"),
        pytest.param("class C {\n  m(): string{ return \"{\"; }\n}", id="method"),
        pytest.param("class C {\n  m(): { a: string }{ return null; }\n}", id="method-object"),
        pytest.param("function m(): { a: string }{ return null; }", id="function-object"),
        pytest.param("function m(): () => void{ return null; }", id="function-type"),
        pytest.param("class C {\n  m(): string\n  {\n    return \"{\";\n  }\n}", id="method-next-line"),
        pytest.param("function m(): string\n{\n  return \"x\";\n}", id="function-next-line"),
    ],
)
def test_parse_a_body_right_after_the_return_type_is_not_part_of_it(source: str) -> None:
    """A `{` after a complete type opens the body, with or without whitespace before it."""
    result = TypeScriptParser().parse(relative_path="rt.ts", content=source + "\n")

    items = [(f.name, f.return_type) for f in result.functions]
    for klass in result.classes:
        items += [(m.name, m.return_type) for m in klass.methods]
    assert len(items) == 1
    name, return_type = items[0]
    assert name == "m"
    assert return_type is not None
    assert "return" not in return_type
    assert not return_type.endswith("{")


def test_parse_exact_return_types_for_bodies_that_follow_immediately() -> None:
    """Exact texts for the adjacent-body cases above."""
    content = """function a(): string{ return "{"; }
function b(): { a: string }{ return null; }
function c(): () => void{ return null; }
class C {
    d(): { a: string }{ return null; }
    e(): string
    {
        return "x";
    }
}
"""
    assert _return_types(content) == [
        ("a", "string", 1),
        ("b", "{ a: string }", 2),
        ("c", "() => void", 3),
        ("d", "{ a: string }", 5),
        ("e", "string", 6),
    ]


def test_parse_callables_without_a_return_annotation_have_no_return_type() -> None:
    """No `:` after the parameters means no return type; a body or arrow is never one."""
    content = """function a() { return { x: 1 }; }
function b(p: string) {}
const c = (x) => x;
const d = (x) => ({ x });
const e = async (x) => { return x; };
class C {
    f() { return { y: 1 }; }
    get g() { return 1; }
}
interface I {
    h(): void;
    i();
}
"""
    result = TypeScriptParser().parse(relative_path="rt.ts", content=content)

    assert [(f.name, f.return_type) for f in result.functions] == [
        ("a", None),
        ("b", None),
        ("c", None),
        ("d", None),
        ("e", None),
    ]
    assert [(m.name, m.return_type) for m in result.classes[0].methods] == [
        ("f", None),
        ("g", None),
    ]
    assert [(m.name, m.return_type) for m in result.interfaces[0].methods] == [
        ("h", "void"),
        ("i", None),
    ]


def test_parse_return_type_metadata_is_preserved_for_object_and_function_types() -> None:
    """`is_async`, parameters, line numbers, and docstrings are unaffected."""
    content = """/** Loads. */
export async function load(id: string): Promise<{ a: string }> { return null; }

/** Runs. */
export const run = async (n: number): Promise<() => void> => null;
const plain = (n: number): { a: string; b: number } => ({ a: "", b: n });
"""
    result = TypeScriptParser().parse(relative_path="rt.ts", content=content)

    assert [
        (f.name, f.parameters, f.return_type, f.is_async, f.line_number, f.docstring)
        for f in result.functions
    ] == [
        ("load", ("id: string",), "Promise<{ a: string }>", True, 2, "Loads."),
        ("run", ("n: number",), "Promise<() => void>", True, 5, "Runs."),
        ("plain", ("n: number",), "{ a: string; b: number }", False, 6, None),
    ]


def test_parse_arrow_detection_uses_the_return_type_boundary() -> None:
    """An arrow is recognized after any annotation; a non-arrow call or conditional is not."""
    content = """const a = (): { x: string; y: number } => ({ x: "", y: 1 });
const b = (): () => void => null;
const c = (): (A | B) => null;
const d = (flag) ? (x) => 1 : 2;
const e = compute(1, 2);
const f = <Foo>(value);
const g = (): string
  => "later";
const h = (x): void => {};
"""
    result = TypeScriptParser().parse(relative_path="rt.ts", content=content)

    assert [(f.name, f.return_type, f.line_number) for f in result.functions] == [
        ("a", "{ x: string; y: number }", 1),
        ("b", "() => void", 2),
        ("c", "(A | B)", 3),
        ("h", "void", 9),
    ]


def test_parse_interface_members_without_semicolons_end_at_the_line_break() -> None:
    """Newline-, comma-, and brace-terminated interface methods each get their own type."""
    content = """interface I {
    a(): R
    b(): { x: number }
    c(): () => void
    d(): A
        | B
    e(): X, f(): Y
    g(): Z }
"""
    assert _return_types(content) == [
        ("a", "R", 2),
        ("b", "{ x: number }", 3),
        ("c", "() => void", 4),
        ("d", "A\n        | B", 5),
        ("e", "X", 7),
        ("f", "Y", 7),
        ("g", "Z", 8),
    ]


@pytest.mark.parametrize(
    "signature",
    [
        pytest.param("function f(a = x<y, b = z>c) {}", id="function"),
        pytest.param("const f = (a = x<y, b = z>c) => {};", id="arrow"),
        pytest.param("class C {\n  f(a = x<y, b = z>c) {}\n}", id="method"),
        pytest.param("interface I {\n  f(a = x<y, b = z>c): void;\n}", id="interface"),
    ],
)
def test_parse_unspaced_comparisons_in_default_values_keep_two_parameters(signature: str) -> None:
    """`x<y, b = z>c` is a comparison, not type arguments: the comma still separates parameters."""
    result = TypeScriptParser().parse(relative_path="rt.ts", content=signature + "\n")

    callables = list(result.functions)
    for klass in result.classes:
        callables += list(klass.methods)
    for interface in result.interfaces:
        callables += list(interface.methods)
    assert [c.parameters for c in callables] == [("a = x<y", "b = z>c")]


def test_parse_generic_arguments_in_default_values_still_group_their_commas() -> None:
    """Real type arguments are unaffected: only a `<` that cannot close as type arguments is not one."""
    content = """function f(a = p<q, r>(s), b = 1, m: Map<string, number> = new Map<string, number>()) {}
function g(a = x <= y, b = u < v, c: Array<Map<string, number>>) {}
"""
    assert [
        f.parameters for f in TypeScriptParser().parse(relative_path="rt.ts", content=content).functions
    ] == [
        ("a = p<q, r>(s)", "b = 1", "m: Map<string, number> = new Map<string, number>()"),
        ("a = x <= y", "b = u < v", "c: Array<Map<string, number>>"),
    ]


# --- member boundaries (M1), declaration headers (M2), and `;` in generic arguments (M3) ----


def _class_methods(content: str, index: int = 0) -> list[tuple[str, str | None, int]]:
    """`(name, return_type, line)` of every method of the `index`-th class in `content`."""
    result = TypeScriptParser().parse(relative_path="cls.ts", content=content)
    return [(m.name, m.return_type, m.line_number) for m in result.classes[index].methods]


def _interface_methods(content: str, index: int = 0) -> list[tuple[str, str | None, int]]:
    """`(name, return_type, line)` of every method of the `index`-th interface in `content`."""
    result = TypeScriptParser().parse(relative_path="ifc.ts", content=content)
    return [(m.name, m.return_type, m.line_number) for m in result.interfaces[index].methods]


def test_parse_class_decorator_calls_and_initializer_calls_are_not_methods() -> None:
    """The reported reproduction: only `real` is a method."""
    content = """class C {
  @Input() name: string;
  cache = new Map<string, number>();
  logger = createLogger('x');
  real(): void {}
}
"""
    assert _class_methods(content) == [("real", "void", 5)]


def test_parse_angular_style_component_keeps_only_real_methods() -> None:
    """A realistic component: decorators, injected fields, accessors, and lifecycle hooks."""
    content = """@Component({
  selector: 'app-x',
})
export class XComponent implements OnInit, OnDestroy {
  @Input() title: string;
  @Input({ required: true }) id!: number;
  @Output() changed = new EventEmitter<string>();
  @ViewChild('ref', { static: true }) ref!: ElementRef<HTMLDivElement>;
  private readonly subject = new Subject<void>();
  readonly items$ = this.store.select(selectItems);
  form = this.fb.group({ name: [''] });

  constructor(private readonly http: HttpClient, private fb: FormBuilder) {}

  @Input() set value(v: string) { this._value = v; }
  get value(): string { return this._value; }

  @HostListener('window:resize', ['$event']) onResize(event: Event): void {}

  ngOnInit(): void {
    this.subject.pipe(debounceTime(10)).subscribe();
  }

  @HostListener('click')
  onClick(): void {}

  ngOnDestroy(): void { this.subject.complete(); }
}
"""
    result = TypeScriptParser().parse(relative_path="x.component.ts", content=content)

    klass = result.classes[0]
    assert (klass.name, klass.base_classes, klass.line_number) == (
        "XComponent",
        ("OnInit", "OnDestroy"),
        4,
    )
    assert [(m.name, m.return_type, m.line_number) for m in klass.methods] == [
        ("constructor", None, 13),
        ("value", None, 15),
        ("value", "string", 16),
        ("onResize", "void", 18),
        ("ngOnInit", "void", 20),
        ("onClick", "void", 25),
        ("ngOnDestroy", "void", 27),
    ]
    assert [p for p in klass.methods[0].parameters] == [
        "private readonly http: HttpClient",
        "private fb: FormBuilder",
    ]


def test_parse_class_field_initializers_with_generic_calls_are_not_methods() -> None:
    """Calls that carry type arguments are still initializers, not declarations."""
    content = """class Store {
  before(): void {}
  a = new Map<string, number>();
  b = createStore<State>();
  c = useMemo<Foo>(() => make(1), []);
  d = Array.from<number>([1, 2]);
  e: Promise<void> = fetchAll<Item, Error>();
  after(): void {}
}
"""
    assert _class_methods(content) == [("before", "void", 2), ("after", "void", 8)]


def test_parse_class_field_initializers_with_ordinary_calls_are_not_methods() -> None:
    """Plain, member, nested, and multi-line calls in initializers add no method."""
    content = """class Svc {
  before(): void {}
  logger = createLogger('x');
  total = compute(1, 2);
  now = Date.now();
  ref = this.run(4);
  nested = outer(inner(1));
  multi = foo(
    1,
    bar(2),
  );
  after(): void {}
}
"""
    assert _class_methods(content) == [("before", "void", 2), ("after", "void", 12)]


def test_parse_class_members_without_semicolons_and_continued_expressions() -> None:
    """A line break ends a member only when it is complete; continued expressions are not methods."""
    content = """class C {
  x = foo(1)
  y = a ||
    compute(2)
  z = cond
    ? one(1)
    : two(2)
  h = () =>
    bar(3)
  real(): void {}
  chain = promise
    .then(fn)
  after(): void {}
}
"""
    assert _class_methods(content) == [("real", "void", 10), ("after", "void", 13)]


def test_parse_class_decorated_methods_are_kept_with_their_own_line_numbers() -> None:
    """Methods behind same-line, stacked, multi-line, bare, and dotted decorators are kept."""
    content = """class C {
  @Get() findAll(): void {}
  @A() @B() both(): void {}
  @ns.Dec(1, 'x')
  multi(): void {}
  @sealed bare(): void {}
  @Input({
    required: true,
  }) prop!: string;
  @HostListener('window:resize', ['$event']) onR(e: Event): void {}
  after(): void {}
}
"""
    assert _class_methods(content) == [
        ("findAll", "void", 2),
        ("both", "void", 3),
        ("multi", "void", 5),
        ("bare", "void", 6),
        ("onR", "void", 10),
        ("after", "void", 11),
    ]


def test_parse_class_methods_with_every_modifier_and_overloads_are_unchanged() -> None:
    """Regression: modifiers in any order, accessors, generators, overloads, and constructors."""
    content = """class C {
  public static async load(): Promise<void> {}
  override foo(): void {}
  static public weird(): void {}
  protected abstract area(): number;
  get size(): number { return 1; }
  set size(v: number) {}
  *gen(): Generator<number> {}
  static async *agen(): AsyncGenerator<number> {}
  f(a: string): void;
  f(a: number): void;
  f(a: any): void {}
  constructor(private a: string) {}
}
"""
    assert _class_methods(content) == [
        ("load", "Promise<void>", 2),
        ("foo", "void", 3),
        ("weird", "void", 4),
        ("area", "number", 5),
        ("size", "number", 6),
        ("size", None, 7),
        ("gen", "Generator<number>", 8),
        ("agen", "AsyncGenerator<number>", 9),
        ("f", "void", 10),
        ("f", "void", 11),
        ("f", "void", 12),
        ("constructor", None, 13),
    ]


def test_parse_interface_members_separated_by_semicolons_commas_and_line_breaks() -> None:
    """Every separator style starts a new member, and overloads are all kept."""
    content = """interface I {
  g(a: string): void;
  g(a: number): void;
  h(): R, i(): S
  j(): T
  k?(): U
}
"""
    assert _interface_methods(content) == [
        ("g", "void", 2),
        ("g", "void", 3),
        ("h", "R", 4),
        ("i", "S", 4),
        ("j", "T", 5),
        ("k", "U", 6),
    ]


def test_parse_calls_inside_an_accepted_method_signature_are_not_methods() -> None:
    """Parameter defaults and return types that contain calls add no separate method."""
    content = """class C {
  m(a = foo(1), b = new Map<string, number>()): typeof import('x') { return null; }
  n(): new () => T { return null; }
  p(c = bar(2)): void {}
}
interface I {
  q(): typeof import('x');
  r(): new () => T;
}
"""
    result = TypeScriptParser().parse(relative_path="sig.ts", content=content)

    assert [(m.name, m.return_type, m.line_number) for m in result.classes[0].methods] == [
        ("m", "typeof import('x')", 2),
        ("n", "new () => T", 3),
        ("p", "void", 4),
    ]
    assert result.classes[0].methods[0].parameters == (
        "a = foo(1)",
        "b = new Map<string, number>()",
    )
    assert [(m.name, m.return_type, m.line_number) for m in result.interfaces[0].methods] == [
        ("q", "typeof import('x')", 7),
        ("r", "new () => T", 8),
    ]


@pytest.mark.parametrize(
    ("header", "bases"),
    [
        pytest.param("class A<\n  T,\n  U\n> {", (), id="multiline-type-parameters"),
        pytest.param("class A<T extends { id: string }> {", (), id="object-constraint"),
        pytest.param(
            "class A<T extends Map<string, { id: string }>, U = Array<{ a: number }>> {",
            (),
            id="nested-generic-constraints",
        ),
        pytest.param("class A<T extends (x: number) => void> {", (), id="arrow-in-constraint"),
        pytest.param("class A<T extends Map<string, number>> {", (), id="nested-generic"),
        pytest.param("class A<\n  T extends { id: string },\n  U\n>\n{", (), id="brace-on-next-line"),
        pytest.param(
            "class A<T extends { id: string }> extends B<{ x: 1 }> implements C<{ y: 2 }>, D {",
            ("B", "C<{ y: 2 }>", "D"),
            id="object-types-in-heritage-clauses",
        ),
        pytest.param(
            "class A<\n  T\n>\n  extends B\n  implements C,\n    D {",
            ("B", "C", "D"),
            id="multiline-heritage",
        ),
        pytest.param("export default abstract class A<\n  T\n> {", (), id="export-default-abstract"),
        pytest.param("declare class A<\n  T\n> {", (), id="declare"),
        pytest.param("class A<T /* c */, // n\n  U> {", (), id="comments-in-header"),
    ],
)
def test_parse_class_headers_with_multiline_or_object_type_parameters(
    header: str, bases: tuple[str, ...]
) -> None:
    """The class and its body are found, with the right bases, whatever the header's shape."""
    lines = header.count("\n")
    content = f"{header}\n  m(): void {{}}\n}}\nfunction tail(): void {{}}\n"
    result = TypeScriptParser().parse(relative_path="h.ts", content=content)

    assert [(c.name, c.base_classes, c.line_number) for c in result.classes] == [("A", bases, 1)]
    assert _class_methods(content) == [("m", "void", lines + 2)]
    assert [f.name for f in result.functions] == ["tail"]


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("interface I<\n  T,\n  U\n> {", id="multiline-type-parameters"),
        pytest.param("interface I<T extends { id: string }> {", id="object-constraint"),
        pytest.param(
            "interface I<T extends Record<string, { a: 1 }>, U = Array<{ b: 2 }>> {",
            id="nested-generic-constraints",
        ),
        pytest.param("interface I<T extends (x: number) => { a: 1 }> {", id="function-constraint"),
        pytest.param("interface I<T extends Map<string, number>> {", id="nested-generic"),
        pytest.param("interface I<\n  T\n>\n{", id="brace-on-next-line"),
        pytest.param("interface I<T> extends Base<{ a: 1 }>, Other {", id="object-type-in-extends"),
        pytest.param("interface I<\n  T\n>\n  extends A,\n    B<{ c: 3 }> {", id="multiline-extends"),
        pytest.param("export interface I<\n  T\n> {", id="export"),
    ],
)
def test_parse_interface_headers_with_multiline_or_object_type_parameters(header: str) -> None:
    """The interface is found with its own members; header types contribute no members."""
    lines = header.count("\n")
    content = f"{header}\n  m(): void;\n  p: string;\n}}\nfunction tail(): void {{}}\n"
    result = TypeScriptParser().parse(relative_path="h.ts", content=content)

    assert [(i.name, i.line_number) for i in result.interfaces] == [("I", 1)]
    assert _interface_methods(content) == [("m", "void", lines + 2)]
    assert [(p.name, p.line_number) for p in result.interfaces[0].properties] == [
        ("p", lines + 3)
    ]
    assert [s.name for s in result.symbols if s.kind is SymbolKind.INTERFACE] == ["I"]
    assert [f.name for f in result.functions] == ["tail"]


def test_parse_the_documented_empty_generic_declarations() -> None:
    """The four shapes from the report, with empty bodies."""
    content = """class A<
  T,
  U
> {}
class B<T extends { id: string }> {}
interface I<
  T,
  U
> {}
interface J<T extends { id: string }> {}
"""
    result = TypeScriptParser().parse(relative_path="empty.ts", content=content)

    assert [(c.name, c.line_number) for c in result.classes] == [("A", 1), ("B", 5)]
    assert [(i.name, i.line_number) for i in result.interfaces] == [("I", 6), ("J", 10)]


def test_parse_an_object_constraint_is_not_taken_for_the_declaration_body() -> None:
    """Members written inside a constraint or a heritage type are not members of the declaration."""
    content = """class A<T extends { run(): void }> extends B<{ go(): void }> {
  real(): void {}
}
interface I<T extends { run(): void }> extends J<{ go(): void; q: 1 }> {
  real(): void;
}
"""
    result = TypeScriptParser().parse(relative_path="constraint.ts", content=content)

    assert _class_methods(content) == [("real", "void", 2)]
    assert _interface_methods(content) == [("real", "void", 5)]
    assert result.interfaces[0].properties == ()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("class A\nfunction f() {}\n", id="class-without-body"),
        pytest.param("interface I\nfunction f() {}\n", id="interface-without-body"),
        pytest.param("class A<T\nfunction f() {}\n", id="unclosed-type-parameters"),
        pytest.param("class A extends\nfunction f() {}\n", id="extends-without-name"),
        pytest.param("class A implements\n{\n}\nfunction f() {}\n", id="implements-without-name"),
    ],
)
def test_parse_a_header_without_a_body_does_not_swallow_later_code(source: str) -> None:
    """The search for a body stops at the header: later braces are not this declaration's."""
    result = TypeScriptParser().parse(relative_path="bad.ts", content=source)

    assert result.classes == ()
    assert result.interfaces == ()
    assert [f.name for f in result.functions] == ["f"]


def test_parse_declarations_after_a_broken_header_are_still_found() -> None:
    """One unclosed header costs only itself."""
    content = "class A<T\nclass B {\n  m(): void {}\n}\n"
    result = TypeScriptParser().parse(relative_path="bad.ts", content=content)

    assert [c.name for c in result.classes] == ["B"]
    assert _class_methods(content) == [("m", "void", 3)]


def test_parse_the_documented_generic_parameter_with_semicolons() -> None:
    """The reported reproduction, exactly."""
    content = """function f(
  x: Record<string, { id: string; name: string }>,
  y: number
): void {}
"""
    result = TypeScriptParser().parse(relative_path="m3.ts", content=content)

    assert [(f.parameters, f.return_type) for f in result.functions] == [
        (("x: Record<string, { id: string; name: string }>", "y: number"), "void")
    ]


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        pytest.param(
            "x: Record<string, { id: string; name: string }>, y: number",
            ("x: Record<string, { id: string; name: string }>", "y: number"),
            id="record-of-object",
        ),
        pytest.param(
            "x: Map<string, Array<{ id: string; n: number }>>, y: number",
            ("x: Map<string, Array<{ id: string; n: number }>>", "y: number"),
            id="nested-generic-object",
        ),
        pytest.param(
            "x: Record<string, { a: string; b: { c: number; d: string } }>, y: number",
            ("x: Record<string, { a: string; b: { c: number; d: string } }>", "y: number"),
            id="nested-object-in-object",
        ),
        pytest.param(
            "x: Foo<{ a: 1; b: 2 }, { c: 3; d: 4 }>, y: string",
            ("x: Foo<{ a: 1; b: 2 }, { c: 3; d: 4 }>", "y: string"),
            id="two-object-arguments",
        ),
        pytest.param(
            "x: Promise<{ a: string; b: number }>, y: number",
            ("x: Promise<{ a: string; b: number }>", "y: number"),
            id="single-object-argument",
        ),
        pytest.param(
            "x: Record<string, { a: string, b: number }>, y: number",
            ("x: Record<string, { a: string, b: number }>", "y: number"),
            id="comma-separated-object",
        ),
        pytest.param(
            "x: Record<string, { run(): void; q?: 1 }>, y: number",
            ("x: Record<string, { run(): void; q?: 1 }>", "y: number"),
            id="object-with-method",
        ),
    ],
)
@pytest.mark.parametrize("form", ["function", "arrow", "method", "interface"])
def test_parse_semicolons_inside_generic_arguments_do_not_split_parameters(
    form: str, parameters: str, expected: tuple[str, ...]
) -> None:
    """A `;` inside `{...}` within type arguments leaves the argument list, and commas, intact."""
    sources = {
        "function": f"function m({parameters}): R {{}}\n",
        "arrow": f"const m = ({parameters}): R => {{}};\n",
        "method": f"class C {{\n  m({parameters}): R {{}}\n}}\n",
        "interface": f"interface I {{\n  m({parameters}): R;\n}}\n",
    }
    result = TypeScriptParser().parse(relative_path="m3.ts", content=sources[form])

    callables = list(result.functions)
    for klass in result.classes:
        callables += list(klass.methods)
    for interface in result.interfaces:
        callables += list(interface.methods)
    assert [c.parameters for c in callables] == [expected]


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        pytest.param("a = x<y, b = z>c", ("a = x<y", "b = z>c"), id="unspaced-comparison"),
        pytest.param("a = 1 < 2, b: number", ("a = 1 < 2", "b: number"), id="spaced-comparison"),
        pytest.param("a = x <= y, b = u < v", ("a = x <= y", "b = u < v"), id="less-or-equal"),
        pytest.param("a = p<q, r>(s), b = 1", ("a = p<q, r>(s)", "b = 1"), id="generic-call-default"),
        pytest.param(
            "a: Map<string, { k: string; v: number }> = new Map<string, { k: string; v: number }>(), b: number",
            (
                "a: Map<string, { k: string; v: number }> = new Map<string, { k: string; v: number }>()",
                "b: number",
            ),
            id="object-generic-default-value",
        ),
        pytest.param(
            "a = x<{ k: 1; v: 2 }, b = z>c",
            ("a = x<{ k: 1; v: 2 }", "b = z>c"),
            id="comparison-next-to-object-with-semicolon",
        ),
    ],
)
@pytest.mark.parametrize("form", ["function", "arrow", "method"])
def test_parse_comparison_and_generic_defaults_keep_their_parameter_boundaries(
    form: str, parameters: str, expected: tuple[str, ...]
) -> None:
    """Comparison handling is unchanged: `<` is type arguments only if it can close as such."""
    sources = {
        "function": f"function m({parameters}): R {{}}\n",
        "arrow": f"const m = ({parameters}): R => {{}};\n",
        "method": f"class C {{\n  m({parameters}): R {{}}\n}}\n",
    }
    result = TypeScriptParser().parse(relative_path="cmp.ts", content=sources[form])

    callables = list(result.functions)
    for klass in result.classes:
        callables += list(klass.methods)
    assert [c.parameters for c in callables] == [expected]


def test_parse_members_named_extends_are_ordinary_members() -> None:
    """`extends` as a member name, with `;` separators, is a property or a method like any other."""
    content = """interface A {
  extends: string;
  name: number;
}
interface B {
  extends(): void;
  other(): string;
}
interface D extends A {
  extends?: string;
  tail: boolean;
}
class C {
  extends(): void {}
  next(): void {}
}
"""
    result = TypeScriptParser().parse(relative_path="ext.ts", content=content)

    assert [(p.name, p.type_annotation) for p in result.interfaces[0].properties] == [
        ("extends", "string"),
        ("name", "number"),
    ]
    assert _interface_methods(content, 1) == [("extends", "void", 6), ("other", "string", 7)]
    assert [(p.name, p.is_optional) for p in result.interfaces[2].properties] == [
        ("extends", True),
        ("tail", False),
    ]
    assert _class_methods(content) == [("extends", "void", 14), ("next", "void", 15)]


def test_parse_a_newline_separated_property_named_extends_after_another_property() -> None:
    """A member named `extends` on its own line is its own property, not a type continuation."""
    content = "interface Cfg {\n  name: string\n  extends?: string\n  other: number\n}\n"
    result = TypeScriptParser().parse(relative_path="ext.ts", content=content)

    assert [(p.name, p.type_annotation) for p in result.interfaces[0].properties] == [
        ("name", "string"),
        ("extends", "string"),
        ("other", "number"),
    ]


_CRLF_SOURCE = """class C<
  T extends { id: string }
> extends B<{ x: 1 }> {
  @Input() name: string;
  cache = new Map<string, number>();
  logger = createLogger('x');
  real(a: Record<string, { id: string; n: number }>, b: number): { a: string } {
    return null;
  }
  after(): () => void { return null; }
}
interface I<
  T,
  U
> {
  g(a: string): void
  h(): R
  p: string
}
function f(
  x: Record<string, { id: string; name: string }>,
  y: number
): void {}
"""


def _structure(content: str) -> dict[str, object]:
    """Everything the parser reports about `content`, with `\r` removed from texts."""
    result = TypeScriptParser().parse(relative_path="s.ts", content=content)

    def clean(value: str | None) -> str | None:
        return None if value is None else value.replace("\r", "")

    def method(m: ParsedFunction) -> tuple[object, ...]:
        return (
            m.name,
            tuple(clean(p) for p in m.parameters),
            clean(m.return_type),
            m.is_async,
            m.line_number,
        )

    return {
        "classes": [
            (c.name, c.base_classes, c.line_number, [method(m) for m in c.methods])
            for c in result.classes
        ],
        "interfaces": [
            (
                i.name,
                i.line_number,
                [method(m) for m in i.methods],
                [(p.name, clean(p.type_annotation), p.line_number) for p in i.properties],
            )
            for i in result.interfaces
        ],
        "functions": [method(f) for f in result.functions],
    }


def test_parse_crlf_input_gives_the_same_structure_as_lf_input() -> None:
    """Windows line endings change no name, boundary, parameter, return type, or line number."""
    lf = _structure(_CRLF_SOURCE)
    crlf = _structure(_CRLF_SOURCE.replace("\n", "\r\n"))

    assert crlf == lf
    classes = lf["classes"]
    assert isinstance(classes, list)
    assert [m[0] for m in classes[0][3]] == ["real", "after"]


def test_parse_crlf_return_types_and_headers_keep_their_exact_text() -> None:
    """Only the line breaks inside a sliced type differ; everything else is identical."""
    content = "class A<\r\n  T\r\n> {\r\n  m(): {\r\n    a: string;\r\n  } {}\r\n}\r\n"
    result = TypeScriptParser().parse(relative_path="crlf.ts", content=content)

    assert [(m.name, m.return_type, m.line_number) for m in result.classes[0].methods] == [
        ("m", "{\r\n    a: string;\r\n  }", 4)
    ]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("class A<", id="class-open-angle"),
        pytest.param("class A<T", id="class-unclosed-angle"),
        pytest.param("class A<T> extends", id="class-extends-eof"),
        pytest.param("class A<T> extends B<", id="class-extends-unclosed-angle"),
        pytest.param("class A implements", id="class-implements-eof"),
        pytest.param("class A extends B implements C,", id="class-trailing-comma"),
        pytest.param("class A {", id="class-unclosed-body"),
        pytest.param("class A {\n  @Input(", id="class-unclosed-decorator"),
        pytest.param("class A {\n  @Input() name: string", id="class-unterminated-field"),
        pytest.param("class A {\n  m(", id="class-unclosed-parameters"),
        pytest.param("class A {\n  m(): {", id="class-unclosed-return-object"),
        pytest.param("class A {\n  m(): () =>", id="class-dangling-arrow"),
        pytest.param("class A {\n  x = foo(1", id="class-unclosed-call"),
        pytest.param("interface I<", id="interface-open-angle"),
        pytest.param("interface I extends", id="interface-extends-eof"),
        pytest.param("interface I {", id="interface-unclosed-body"),
        pytest.param("interface I {\n  m(): R,", id="interface-trailing-comma"),
        pytest.param("interface I {\n  m(a: Record<string, { a: string;", id="interface-unclosed-generic"),
        pytest.param("function f(x: Record<string, { a: string;", id="function-unclosed-generic"),
        pytest.param("@", id="lone-at-sign"),
        pytest.param("@Dec(", id="lone-decorator"),
        pytest.param("class", id="lone-class-keyword"),
        pytest.param("interface", id="lone-interface-keyword"),
        pytest.param("class A<T extends {", id="class-unclosed-constraint"),
        pytest.param("class A {\n  `unterminated template", id="class-unterminated-template"),
    ],
)
def test_parse_malformed_input_never_raises(source: str) -> None:
    """Incomplete or broken syntax yields a result (possibly empty), never an exception."""
    for text in (source, source + "\n", source.replace("\n", "\r\n")):
        result = TypeScriptParser().parse(relative_path="bad.ts", content=text)

        assert result.relative_path == "bad.ts"


def test_parse_large_realistic_class_in_reasonable_time() -> None:
    """Parsing is roughly linear: thousands of decorated members and initializers take well under
    a second on a developer machine; the bound here is deliberately generous."""
    members = "".join(
        f"  @Input() f{i}: string;\n"
        f"  c{i} = new Map<string, number>();\n"
        f"  m{i}(a: string, b: number): void {{ foo(a); }}\n"
        for i in range(1500)
    )
    content = "class C {\n" + members + "}\n"

    started = time.perf_counter()
    result = TypeScriptParser().parse(relative_path="big.ts", content=content)
    elapsed = time.perf_counter() - started

    assert [m.name for m in result.classes[0].methods] == [f"m{i}" for i in range(1500)]
    assert elapsed < 10.0


def test_parse_many_multiline_generic_declarations_in_reasonable_time() -> None:
    """Hundreds of multi-line generic classes and interfaces are found, and quickly."""
    content = "".join(
        f"class K{i}<\n  T extends {{ id: string }}\n> extends B<{{ x: 1 }}> {{\n  m(): void {{}}\n}}\n"
        f"interface I{i}<\n  T,\n  U\n> {{\n  m(a: T): U;\n"
        f"  p: Record<string, {{ a: string; b: number }}>;\n}}\n"
        for i in range(400)
    )
    started = time.perf_counter()
    result = TypeScriptParser().parse(relative_path="many.ts", content=content)
    elapsed = time.perf_counter() - started

    assert len(result.classes) == 400
    assert len(result.interfaces) == 400
    assert elapsed < 10.0


def test_parse_repeated_unclosed_headers_in_reasonable_time() -> None:
    """Many broken headers in a row are skipped; the cost is bounded for realistic sizes."""
    content = "class A<\n" * 500 + "interface I<T\n" * 500 + "class B {\n  m(): void {}\n}\n"

    started = time.perf_counter()
    result = TypeScriptParser().parse(relative_path="broken.ts", content=content)
    elapsed = time.perf_counter() - started

    assert [c.name for c in result.classes] == ["B"]
    assert elapsed < 10.0


def test_parse_class_decorators_with_type_arguments_or_spaces_before_the_arguments() -> None:
    """A method after a same-line decorator is kept whatever the decorator call looks like."""
    content = """class C {
  @Dec () spaced(): void {}
  @Dec<T>() generic(): void {}
  @Dec<Map<string, number>> ({ a: 1 }) nested(): void {}
  @Field<Type>({ a: 1 }) f!: string;
  @Dec<T>() @Other () both(): void {}
  after(): void {}
}
"""
    assert _class_methods(content) == [
        ("spaced", "void", 2),
        ("generic", "void", 3),
        ("nested", "void", 4),
        ("both", "void", 6),
        ("after", "void", 7),
    ]


def test_parse_class_arrow_field_followed_by_parenthesized_text_is_not_a_decorated_method() -> None:
    """The `>` of an arrow before `(...)` is not a decorator's type arguments."""
    content = """class C {
  h = () => (a);
  g = () =>
    (b)
  real(): void {}
}
"""
    assert _class_methods(content) == [("real", "void", 5)]


# --- members named `extends`, and conditional types that really continue on the next line ----


def test_parse_the_documented_newline_separated_property_named_extends() -> None:
    """The reported property reproduction: three properties, with lines and optionality."""
    content = "interface Config {\n  name: string\n  extends?: string\n  other: number\n}\n"
    result = TypeScriptParser().parse(relative_path="ext.ts", content=content)

    assert [
        (p.name, p.type_annotation, p.is_optional, p.line_number)
        for p in result.interfaces[0].properties
    ] == [
        ("name", "string", False, 2),
        ("extends", "string", True, 3),
        ("other", "number", False, 4),
    ]


def test_parse_the_documented_newline_separated_method_named_extends() -> None:
    """The reported method reproduction: two methods, and `a` keeps its own return type."""
    content = "interface Example {\n  a(): R\n  extends(): void\n}\n"

    assert _interface_methods(content) == [("a", "R", 2), ("extends", "void", 3)]


@pytest.mark.parametrize(
    ("member", "optional"),
    [
        pytest.param("extends: string", False, id="plain"),
        pytest.param("extends?: string", True, id="optional"),
        pytest.param("extends ?: string", True, id="space-before-question-mark"),
        pytest.param("extends : string", False, id="space-before-colon"),
        pytest.param("extends?:string", True, id="no-space-after-colon"),
    ],
)
def test_parse_property_named_extends_between_newline_separated_properties(
    member: str, optional: bool
) -> None:
    """Whatever the spacing, a line that starts a property named `extends` ends the previous one."""
    content = f"interface I {{\n  name: string\n  {member}\n  other: number\n}}\n"
    result = TypeScriptParser().parse(relative_path="ext.ts", content=content)

    assert [
        (p.name, p.type_annotation, p.is_optional, p.line_number)
        for p in result.interfaces[0].properties
    ] == [
        ("name", "string", False, 2),
        ("extends", "string", optional, 3),
        ("other", "number", False, 4),
    ]


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        pytest.param("extends(): void", ("extends", "void"), id="plain"),
        pytest.param("extends?(): void", ("extends", "void"), id="optional"),
        pytest.param("extends<T>(x: T): T", ("extends", "T"), id="generic"),
        pytest.param("extends(a: string, b?: number): R", ("extends", "R"), id="parameters"),
        pytest.param("extends(): { a: string }", ("extends", "{ a: string }"), id="object-return"),
        pytest.param("extends(): () => void", ("extends", "() => void"), id="function-return"),
    ],
)
def test_parse_method_named_extends_after_a_newline_separated_method(
    member: str, expected: tuple[str, str]
) -> None:
    """A line that starts a method named `extends` ends the previous method's return type."""
    content = f"interface I {{\n  a(): R\n  {member}\n  b(): S\n}}\n"

    assert _interface_methods(content) == [
        ("a", "R", 2),
        (expected[0], expected[1], 3),
        ("b", "S", 4),
    ]


def test_parse_method_named_extends_without_a_return_type_or_separator() -> None:
    """`extends()` followed by a line break is a method with no annotation."""
    content = "interface I {\n  a(): R\n  extends()\n  b(): S\n}\n"

    assert _interface_methods(content) == [("a", "R", 2), ("extends", None, 3), ("b", "S", 4)]


def test_parse_class_methods_named_extends_after_newline_terminated_members() -> None:
    """In a class body too: after a method, and after a field with no semicolon."""
    content = """class C {
  a(): R { return null; }
  extends(): void {}
  name: string
  extends2(): void {}
  field = 1
  extends<T>(x: T): T { return x; }
}
"""
    assert _class_methods(content) == [
        ("a", "R", 2),
        ("extends", "void", 3),
        ("extends2", "void", 5),
        ("extends", "T", 7),
    ]


def test_parse_member_named_extends_under_an_extends_clause() -> None:
    """The `extends` keyword of the header and members named `extends` do not interfere."""
    content = """interface D extends A<{ x: 1 }>, B {
  name: string
  extends?: string
  run(): void
  extends2(): R
}
class E extends F implements G {
  extends(): void {}
}
"""
    result = TypeScriptParser().parse(relative_path="ext.ts", content=content)

    assert [(p.name, p.type_annotation) for p in result.interfaces[0].properties] == [
        ("name", "string"),
        ("extends", "string"),
    ]
    assert [(m.name, m.return_type) for m in result.interfaces[0].methods] == [
        ("run", "void"),
        ("extends2", "R"),
    ]
    assert [(c.name, c.base_classes) for c in result.classes] == [("E", ("F", "G"))]
    assert [m.name for m in result.classes[0].methods] == ["extends"]


@pytest.mark.parametrize(
    ("conditional", "collapsed"),
    [
        pytest.param(
            "T\n    extends string\n    ? 1\n    : 2",
            "T extends string ? 1 : 2",
            id="plain",
        ),
        pytest.param(
            "T\n    extends (infer U)[]\n    ? U\n    : never",
            "T extends (infer U)[] ? U : never",
            id="parenthesized-infer",
        ),
        pytest.param(
            "T\n    extends (x: number) => infer R\n    ? R\n    : never",
            "T extends (x: number) => infer R ? R : never",
            id="function-type",
        ),
        pytest.param(
            "T\n    extends { x: infer X }\n    ? X\n    : never",
            "T extends { x: infer X } ? X : never",
            id="object-type",
        ),
        pytest.param(
            "T\n    extends [infer H, ...infer Rest]\n    ? H\n    : never",
            "T extends [infer H, ...infer Rest] ? H : never",
            id="tuple",
        ),
        pytest.param(
            "T\n    extends(infer U)[]\n    ? U\n    : never",
            "T extends(infer U)[] ? U : never",
            id="unspaced-parenthesis",
        ),
        pytest.param(
            "T\n    extends string\n    ? 1\n    : T\n      extends number\n      ? 2\n      : 3",
            "T extends string ? 1 : T extends number ? 2 : 3",
            id="nested-chain",
        ),
        pytest.param("T extends\n    string\n    ? 1\n    : 2", "T extends string ? 1 : 2", id="type-on-next-line"),
    ],
)
def test_parse_conditional_property_types_continue_across_lines(
    conditional: str, collapsed: str
) -> None:
    """A real conditional type keeps its `extends` line; the next property still starts afresh."""
    content = f"interface I {{\n  a: {conditional}\n  b: number\n}}\n"
    result = TypeScriptParser().parse(relative_path="cond.ts", content=content)

    properties = result.interfaces[0].properties
    assert [(p.name, p.type_annotation) for p in properties] == [("a", collapsed), ("b", "number")]
    assert properties[1].line_number == content.count("\n", 0, content.index("  b: number")) + 1


def test_parse_a_conditional_type_followed_by_a_member_named_extends() -> None:
    """The two readings meet: the conditional's `extends` continues, the member's does not."""
    content = """interface I {
  a: T
    extends string
    ? 1
    : 2
  extends?: boolean
  b: number
}
"""
    result = TypeScriptParser().parse(relative_path="cond.ts", content=content)

    assert [(p.name, p.type_annotation, p.line_number) for p in result.interfaces[0].properties] == [
        ("a", "T extends string ? 1 : 2", 2),
        ("extends", "boolean", 6),
        ("b", "number", 7),
    ]


CONDITIONAL_RETURN_TYPES = [
    pytest.param("T\n    extends string\n      ? A\n      : B", id="plain"),
    pytest.param("T\n  extends (infer U)[]\n  ? U\n  : never", id="parenthesized-infer"),
    pytest.param("T extends string\n    ? A\n    : B", id="keyword-on-first-line"),
    pytest.param("T\n  extends { a: 1 }\n  ? X\n  : Y", id="object-type"),
    pytest.param("T\n  extends(infer U)[]\n  ? U\n  : never", id="unspaced-parenthesis"),
]


@pytest.mark.parametrize("return_type", CONDITIONAL_RETURN_TYPES)
@pytest.mark.parametrize("kind", ["function", "arrow", "method", "interface"])
def test_parse_conditional_return_types_continue_across_lines(kind: str, return_type: str) -> None:
    """A multi-line conditional return type is one annotation, with its exact original text."""
    content, _ = _callable_forms(return_type)[kind]

    assert [(name, rt) for name, rt, _ in _return_types(content)] == [
        ("m", return_type),
        ("n", "void"),
    ]


def test_parse_a_conditional_return_type_followed_by_a_method_named_extends() -> None:
    """The conditional's `extends` line continues the type; the method's does not."""
    content = """interface I {
  m(): T
    extends string
      ? A
      : B
  extends(): void
  n(): S
}
"""
    assert _interface_methods(content) == [
        ("m", "T\n    extends string\n      ? A\n      : B", 2),
        ("extends", "void", 6),
        ("n", "S", 7),
    ]


def test_parse_a_type_alias_with_a_conditional_type_does_not_disturb_neighbours() -> None:
    """The documented alias, with declarations around it that use members named `extends`."""
    content = """type Result<T> =
  T extends string
    ? string
    : number
interface After {
  p: string
  extends?: boolean
}
function tail(): void {}
"""
    result = TypeScriptParser().parse(relative_path="alias.ts", content=content)

    assert [(s.name, s.kind, s.line_number) for s in result.symbols if s.name == "Result"] == [
        ("Result", SymbolKind.TYPE_ALIAS, 1)
    ]
    assert [(p.name, p.type_annotation) for p in result.interfaces[0].properties] == [
        ("p", "string"),
        ("extends", "boolean"),
    ]
    assert [(f.name, f.line_number) for f in result.functions] == [("tail", 9)]
