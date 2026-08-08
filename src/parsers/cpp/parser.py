"""`Parser` implementation for C++ source files.

Only in-class-body member declarations are collected as a class's methods; an out-of-class
definition (`ReturnType ClassName::method(...) { ... }`) is not matched back to its class and so
does not appear at all, a deliberate scope limitation rather than an attempt at full name
resolution. "Exported" here means the C++20 `export` keyword prefixing a declaration; ordinary
(pre-modules) C++ has no such concept, so `exports` is typically empty, matching this package's
general "where applicable" framing for the concept.
"""

import re

from src.domain.entities import SourceLanguage

from ..base import (
    ParsedClass,
    ParsedExport,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
    ParsedSymbol,
    Parser,
    ParseResult,
    SymbolKind,
    build_file_metadata,
    find_matching_brace,
    find_matching_paren,
    has_extension,
    is_top_level_of_span,
    leading_comment_lines,
    line_number_at,
    require_relative_path,
    split_top_level,
    strip_c_style_comments,
)

#: File extensions `CppParser.supports` recognizes.
_EXTENSIONS = (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h")

#: Optional leading C++20 `export` keyword, shared by declaration patterns that support it.
_EXPORT = r"(?:export\s+)?"

_INCLUDE_PATTERN = re.compile(
    r'^[ \t]*#\s*include\s*(?:<(?P<angle>[^>]+)>|"(?P<quoted>[^"]+)")', re.MULTILINE
)
_MODULE_IMPORT_PATTERN = re.compile(rf"^[ \t]*{_EXPORT}import\s+(?P<name>[\w.]+)\s*;", re.MULTILINE)
_NAMESPACE_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:inline\s+)?namespace\s+(?P<name>[\w:]+)\s*\{{", re.MULTILINE
)
_CLASS_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:template\s*<[^>]*>\s*)?(?:class|struct)\s+(?P<name>\w+)"
    r"(?:\s+final)?"
    r"(?:\s*:\s*(?P<bases>[^{]+?))?"
    r"\s*\{",
    re.MULTILINE,
)
_ENUM_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}enum(?:\s+class|\s+struct)?\s+(?P<name>\w+)", re.MULTILINE
)
_USING_ALIAS_PATTERN = re.compile(rf"^[ \t]*{_EXPORT}using\s+(?P<name>\w+)\s*=", re.MULTILINE)
_TYPEDEF_PATTERN = re.compile(r"^[ \t]*typedef\s+.+?\b(?P<name>\w+)\s*;", re.MULTILINE)
_METHOD_PATTERN = re.compile(r"^[ \t]*(?P<prefix>[^{};()\n]*?)(?P<name>~?\w+)\s*\(", re.MULTILINE)
_ACCESS_SPECIFIER_PATTERN = re.compile(r"^[ \t]*(?:public|private|protected)\s*:\s*$")


class CppParser(Parser):
    """Extracts modules, classes, functions, imports, exports, and symbols from C++ source."""

    @property
    def language(self) -> SourceLanguage:
        """The language this parser produces `ParseResult` entries for.

        Returns:
            `SourceLanguage.CPP`.
        """
        return SourceLanguage.CPP

    def supports(self, relative_path: str) -> bool:
        """Report whether `relative_path` has a C++ source or header extension.

        Args:
            relative_path: Path of the candidate file.

        Returns:
            True if `relative_path` ends with a recognized C++ extension.
        """
        return has_extension(relative_path, _EXTENSIONS)

    def parse(self, *, relative_path: str, content: str) -> ParseResult:
        """Parse C++ `content` into a `ParseResult`.

        Args:
            relative_path: Path of the file `content` was read from.
            content: The file's full text content.

        Returns:
            A successful result. This lightweight scan does not itself validate C++'s grammar,
            so this parser has no failure path of its own.

        Raises:
            ValidationError: If `relative_path` is blank.
        """
        require_relative_path(relative_path)
        scan = strip_c_style_comments(content)
        lines = content.splitlines()
        metadata = build_file_metadata(
            relative_path=relative_path, language=SourceLanguage.CPP, content=content
        )

        modules = _extract_namespaces(content, scan)
        imports = _extract_imports(content, scan)
        classes, class_spans = _extract_classes(content, scan, lines)
        functions = _extract_functions(content, scan, lines, class_spans)
        enums = _extract_simple(content, scan, _ENUM_PATTERN)
        type_aliases = _extract_type_aliases(content, scan)

        symbols = _build_symbols(modules, classes, functions, enums, type_aliases)
        exports = _build_exports(lines, classes, functions, enums, type_aliases)

        return ParseResult.ok(
            relative_path=relative_path,
            language=SourceLanguage.CPP,
            metadata=metadata,
            modules=modules,
            classes=classes,
            functions=functions,
            imports=imports,
            exports=exports,
            symbols=symbols,
        )


def _extract_namespaces(content: str, scan: str) -> tuple[ParsedModule, ...]:
    """Collect every `namespace` block declaration.

    A C++17 nested namespace (`namespace A::B { ... }`) is reported as one `ParsedModule` whose
    name is the whole `"A::B"` path, rather than three separate entries.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        Every named namespace, in source order. An anonymous `namespace { ... }` has no name to
        report and is skipped.
    """
    return tuple(
        ParsedModule(name=match["name"], line_number=line_number_at(content, match.start()))
        for match in _NAMESPACE_PATTERN.finditer(scan)
    )


def _extract_imports(content: str, scan: str) -> tuple[ParsedImport, ...]:
    """Collect every `#include` directive and C++20 `import` declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        Every include/import found, in source order.
    """
    imports: list[ParsedImport] = []
    for match in _INCLUDE_PATTERN.finditer(scan):
        line = line_number_at(content, match.start())
        if match["angle"] is not None:
            imports.append(ParsedImport(module=match["angle"], is_relative=False, line_number=line))
        else:
            imports.append(ParsedImport(module=match["quoted"], is_relative=True, line_number=line))
    for match in _MODULE_IMPORT_PATTERN.finditer(scan):
        imports.append(
            ParsedImport(module=match["name"], line_number=line_number_at(content, match.start()))
        )
    return tuple(imports)


def _extract_classes(
    content: str, scan: str, lines: list[str]
) -> tuple[tuple[ParsedClass, ...], tuple[tuple[int, int], ...]]:
    """Collect every `class`/`struct` declaration and its methods.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        lines: `content` split into lines.

    Returns:
        A pair of: every class found, and every class body's `(start, end)` span (used by
        `_extract_functions` to exclude methods from the free-function scan).
    """
    classes: list[ParsedClass] = []
    spans: list[tuple[int, int]] = []

    for match in _CLASS_PATTERN.finditer(scan):
        open_index = match.end() - 1
        close_index = find_matching_brace(scan, open_index)
        body_start = open_index + 1
        spans.append((body_start, close_index))

        base_classes = _parse_base_list(match["bases"]) if match["bases"] else ()
        methods = tuple(
            _build_method(content, scan, method_match)
            for method_match in _METHOD_PATTERN.finditer(scan, body_start, close_index)
            if is_top_level_of_span(scan, body_start, method_match.start())
            and not _ACCESS_SPECIFIER_PATTERN.match(
                lines[line_number_at(content, method_match.start()) - 1]
            )
        )

        line = line_number_at(content, match.start())
        classes.append(
            ParsedClass(
                name=match["name"],
                base_classes=base_classes,
                methods=methods,
                docstring=leading_comment_lines(lines, line, prefix="///"),
                line_number=line,
            )
        )

    return tuple(classes), tuple(spans)


def _parse_base_list(bases: str) -> tuple[str, ...]:
    """Parse a `: public Base1, private Base2` inheritance clause into plain type names.

    Args:
        bases: The text between the class name (or `final`) and the class body's opening `{`,
            not including the leading `:`.

    Returns:
        Each base type name, with any `public`/`private`/`protected`/`virtual` access or
        inheritance-mode keyword stripped.
    """
    names: list[str] = []
    for entry in split_top_level(bases):
        words = entry.split()
        words = [
            word for word in words if word not in ("public", "private", "protected", "virtual")
        ]
        if words:
            names.append(" ".join(words))
    return tuple(names)


def _build_method(content: str, scan: str, match: re.Match[str]) -> ParsedFunction:
    """Build a `ParsedFunction` for one member found inside a class/struct body.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        match: A `_METHOD_PATTERN` match.

    Returns:
        The corresponding `ParsedFunction`, with `is_method=True`.
    """
    params_open = match.end() - 1
    params_close = find_matching_paren(scan, params_open)
    parameters = split_top_level(content[params_open + 1 : params_close])
    prefix = match["prefix"]
    return ParsedFunction(
        name=match["name"],
        parameters=parameters,
        return_type=_clean_return_type(prefix),
        is_method=True,
        line_number=line_number_at(content, match.start()),
    )


def _clean_return_type(prefix: str) -> str | None:
    """Reduce a method's raw pre-name text to a plain return type, when there is one.

    Args:
        prefix: The text captured before a method's name, e.g. `"virtual const std::string& "`.

    Returns:
        `prefix` with common declaration-specifier keywords removed and whitespace collapsed, or
        None if nothing but those keywords (or nothing at all) was present, e.g. for a
        constructor or destructor.
    """
    words = prefix.split()
    words = [
        word
        for word in words
        if word not in ("virtual", "static", "explicit", "inline", "friend", "constexpr")
    ]
    return " ".join(words) if words else None


def _extract_functions(
    content: str, scan: str, lines: list[str], class_spans: tuple[tuple[int, int], ...]
) -> tuple[ParsedFunction, ...]:
    """Collect every namespace- or global-scope function declaration.

    A candidate is accepted only when it sits at "opaque" brace depth 0: not nested inside any
    class/struct body (excluded via `class_spans`), function body, or control-flow block
    (`if`/`for`/`while`/`switch`/`catch`) -- `namespace` blocks are the one construct treated as
    transparent, since a free function declared inside one is still a free function. Without
    this check, a plain call statement like `return computeTotal(a, b);` inside some other
    function's body would otherwise look identical to a new top-level function declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        lines: `content` split into lines.
        class_spans: Class body spans already found by `_extract_classes`, to exclude methods.

    Returns:
        Every free function found, in source order.
    """
    namespace_opens = {match.end() - 1 for match in _NAMESPACE_PATTERN.finditer(scan)}
    opaque_depths = _compute_opaque_depths(scan, namespace_opens)

    functions: list[ParsedFunction] = []
    for match in _METHOD_PATTERN.finditer(scan):
        if any(start <= match.start() < end for start, end in class_spans):
            continue
        if opaque_depths[match.start()] != 0:
            continue
        prefix = match["prefix"].strip()
        if not prefix:
            continue
        params_open = match.end() - 1
        params_close = find_matching_paren(scan, params_open)
        parameters = split_top_level(content[params_open + 1 : params_close])
        line = line_number_at(content, match.start())
        functions.append(
            ParsedFunction(
                name=match["name"],
                parameters=parameters,
                return_type=_clean_return_type(match["prefix"]),
                docstring=leading_comment_lines(lines, line, prefix="///"),
                line_number=line,
            )
        )
    return tuple(functions)


def _compute_opaque_depths(scan: str, namespace_opens: set[int]) -> list[int]:
    """Compute the opaque-brace nesting depth at every position in `scan`.

    A `{` is "opaque" unless its position is in `namespace_opens`: a `namespace` block is
    transparent (declaring a free function directly inside one still counts as free-scope), but
    a function body, `if`/`for`/`while`/`switch`/`catch` block, class body, or anything else is
    not, and increases the depth for everything nested inside it.

    Args:
        scan: `content` with comments blanked out.
        namespace_opens: Index of the `{` for every `namespace` block already found.

    Returns:
        A list the same length as `scan` plus one, where entry `i` is the opaque depth
        immediately before the character at index `i` is processed (entry `len(scan)` is the
        final depth, included for a match that starts at the very end of the text).
    """
    depths = [0] * (len(scan) + 1)
    stack: list[bool] = []
    for index, character in enumerate(scan):
        depths[index] = sum(stack)
        if character == "{":
            stack.append(index not in namespace_opens)
        elif character == "}" and stack:
            stack.pop()
    depths[len(scan)] = sum(stack)
    return depths


def _extract_simple(content: str, scan: str, pattern: re.Pattern[str]) -> dict[str, int]:
    """Collect every match of a single-capture-group declaration pattern.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        pattern: A compiled pattern with a `name` capture group.

    Returns:
        A mapping of declared name to 1-indexed declaration line, in source order.
    """
    return {
        match["name"]: line_number_at(content, match.start()) for match in pattern.finditer(scan)
    }


def _extract_type_aliases(content: str, scan: str) -> dict[str, int]:
    """Collect every `using Name = ...;` alias and `typedef ... Name;` declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        A mapping of type name to 1-indexed declaration line, in source order.
    """
    aliases = _extract_simple(content, scan, _USING_ALIAS_PATTERN)
    aliases.update(_extract_simple(content, scan, _TYPEDEF_PATTERN))
    return aliases


def _build_symbols(
    modules: tuple[ParsedModule, ...],
    classes: tuple[ParsedClass, ...],
    functions: tuple[ParsedFunction, ...],
    enums: dict[str, int],
    type_aliases: dict[str, int],
) -> tuple[ParsedSymbol, ...]:
    """Build the flat symbol table from every already-extracted construct.

    Args:
        modules: Namespaces already extracted.
        classes: Classes/structs already extracted.
        functions: Free functions already extracted.
        enums: Enum names and line numbers.
        type_aliases: Type alias names and line numbers.

    Returns:
        One `ParsedSymbol` per construct found.
    """
    symbols: list[ParsedSymbol] = [
        ParsedSymbol(name=module.name, kind=SymbolKind.NAMESPACE, line_number=module.line_number)
        for module in modules
    ]
    symbols.extend(
        ParsedSymbol(name=cls.name, kind=SymbolKind.CLASS, line_number=cls.line_number)
        for cls in classes
    )
    symbols.extend(
        ParsedSymbol(name=method.name, kind=SymbolKind.METHOD, line_number=method.line_number)
        for cls in classes
        for method in cls.methods
    )
    symbols.extend(
        ParsedSymbol(name=function.name, kind=SymbolKind.FUNCTION, line_number=function.line_number)
        for function in functions
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.ENUM, line_number=line)
        for name, line in enums.items()
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.TYPE_ALIAS, line_number=line)
        for name, line in type_aliases.items()
    )
    return tuple(symbols)


def _build_exports(
    lines: list[str],
    classes: tuple[ParsedClass, ...],
    functions: tuple[ParsedFunction, ...],
    enums: dict[str, int],
    type_aliases: dict[str, int],
) -> tuple[ParsedExport, ...]:
    """Build the export list from every declaration marked with the C++20 `export` keyword.

    Args:
        lines: The original file content, split into lines.
        classes: Classes/structs already extracted.
        functions: Free functions already extracted.
        enums: Enum names and line numbers.
        type_aliases: Type alias names and line numbers.

    Returns:
        One `ParsedExport` per top-level declaration whose line starts with `export`.
    """
    candidates: dict[str, int] = {cls.name: cls.line_number for cls in classes}
    candidates.update({function.name: function.line_number for function in functions})
    candidates.update(enums)
    candidates.update(type_aliases)
    return tuple(
        ParsedExport(name=name, line_number=line)
        for name, line in candidates.items()
        if lines[line - 1].lstrip().startswith("export")
    )
