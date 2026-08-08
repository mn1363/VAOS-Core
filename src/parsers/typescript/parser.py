"""`Parser` implementation for TypeScript source files.

`interface` declarations are reported as `SymbolKind.INTERFACE` symbols rather than
`ParsedClass` entries, for the same reason Rust's `trait` is: an interface has no method bodies
of its own. `class`, unlike `interface`, is reported as a `ParsedClass`, with `base_classes`
combining whatever the class both `extends` and `implements`, since `ParsedClass` does not
distinguish the two relationships.

This scan tracks each `class` body's span so a method found inside one is not also counted as a
free function, but it does not compute full nesting depth for arbitrary block nesting -- a named
`function` declared *inside another function's* body (legal in TypeScript, if unusual) is still
reported as a free function rather than being excluded as nested. This mirrors the same
lightweight-scan trade-off this package's other three regular-expression-based parsers make.
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
    line_number_at,
    require_relative_path,
    split_top_level,
    strip_c_style_comments,
)

#: File extensions `TypeScriptParser.supports` recognizes.
_EXTENSIONS = (".ts", ".tsx")

#: Optional `export`/`export default` prefix, shared by most declaration patterns.
_EXPORT = r"(?:export\s+(?:default\s+)?)?"

_IMPORT_PATTERN = re.compile(
    r"^[ \t]*import\s+(?:type\s+)?"
    r"(?:(?P<default>[\w$]+)\s*,?\s*)?"
    r"(?:\*\s+as\s+(?P<namespace>[\w$]+)\s*)?"
    r"(?:\{(?P<named>[^}]*)\}\s*)?"
    r"(?:from\s+)?"
    r"['\"](?P<path>[^'\"]+)['\"]",
    re.MULTILINE,
)
_EXPORT_BRACE_PATTERN = re.compile(
    r"^[ \t]*export\s*\{(?P<body>[^}]*)\}(?:\s*from\s+['\"][^'\"]+['\"])?\s*;?", re.MULTILINE
)
_EXPORT_STAR_PATTERN = re.compile(
    r"^[ \t]*export\s*\*\s*(?:as\s+(?P<alias>[\w$]+)\s*)?from\s+['\"][^'\"]+['\"]", re.MULTILINE
)
_EXPORT_DEFAULT_PATTERN = re.compile(r"^[ \t]*export\s+default\b", re.MULTILINE)
_NAMED_DEFAULT_PATTERN = re.compile(
    r"^[ \t]*export\s+default\s+(?:async\s+)?(?:abstract\s+)?(?:function|class)\s+[\w$]"
)
_NAMESPACE_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:namespace|module)\s+(?P<name>[\w$.]+)\s*\{{", re.MULTILINE
)
_CLASS_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:abstract\s+)?class\s+(?P<name>[\w$]+)(?:<[^>]*>)?"
    r"(?:\s+extends\s+(?P<extends>[\w$.]+)(?:<[^>]*>)?)?"
    r"(?:\s+implements\s+(?P<implements>[^{]+?))?"
    r"\s*\{",
    re.MULTILINE,
)
_METHOD_PATTERN = re.compile(
    r"^[ \t]*(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:readonly\s+)?"
    r"(?:abstract\s+)?(?:async\s+)?(?:get\s+|set\s+)?(?:\*\s*)?"
    r"(?P<name>[\w$]+)\??\s*(?:<[^>]*>)?\s*\(",
    re.MULTILINE,
)
_INTERFACE_PATTERN = re.compile(rf"^[ \t]*{_EXPORT}interface\s+(?P<name>[\w$]+)", re.MULTILINE)
_TYPE_ALIAS_PATTERN = re.compile(rf"^[ \t]*{_EXPORT}type\s+(?P<name>[\w$]+)", re.MULTILINE)
_ENUM_PATTERN = re.compile(rf"^[ \t]*{_EXPORT}(?:const\s+)?enum\s+(?P<name>[\w$]+)", re.MULTILINE)
_FUNCTION_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?P<async>async\s+)?function\s*\*?\s+(?P<name>[\w$]+)", re.MULTILINE
)
_ARROW_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:const|let)\s+(?P<name>[\w$]+)\s*(?::[^=]+?)?=\s*(?P<async>async\s+)?\(",
    re.MULTILINE,
)
_CONST_LET_VAR_NAME_PATTERN = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?(?P<keyword>const|let|var)\s+(?P<name>[\w$]+)",
    re.MULTILINE,
)


class TypeScriptParser(Parser):
    """Extracts modules, classes, functions, imports, exports, and symbols from TypeScript."""

    @property
    def language(self) -> SourceLanguage:
        """The language this parser produces `ParseResult` entries for.

        Returns:
            `SourceLanguage.TYPESCRIPT`.
        """
        return SourceLanguage.TYPESCRIPT

    def supports(self, relative_path: str) -> bool:
        """Report whether `relative_path` has a TypeScript extension.

        Args:
            relative_path: Path of the candidate file.

        Returns:
            True if `relative_path` ends with `.ts` or `.tsx`.
        """
        return has_extension(relative_path, _EXTENSIONS)

    def parse(self, *, relative_path: str, content: str) -> ParseResult:
        """Parse TypeScript `content` into a `ParseResult`.

        Args:
            relative_path: Path of the file `content` was read from.
            content: The file's full text content.

        Returns:
            A successful result. This lightweight scan does not itself validate TypeScript's
            grammar, so this parser has no failure path of its own.

        Raises:
            ValidationError: If `relative_path` is blank.
        """
        require_relative_path(relative_path)
        scan = strip_c_style_comments(content)
        lines = content.splitlines()
        metadata = build_file_metadata(
            relative_path=relative_path, language=SourceLanguage.TYPESCRIPT, content=content
        )

        modules = _extract_namespaces(content, scan, lines)
        imports = _extract_imports(content, scan)
        classes, class_spans = _extract_classes(content, scan, lines)
        arrow_names = {
            match["name"] for match in _ARROW_PATTERN.finditer(scan) if _is_arrow(scan, match)
        }
        functions = _extract_functions(content, scan, lines, class_spans)
        interfaces = _extract_simple(content, scan, _INTERFACE_PATTERN)
        type_aliases = _extract_simple(content, scan, _TYPE_ALIAS_PATTERN)
        enums = _extract_simple(content, scan, _ENUM_PATTERN)
        consts, lets, vars_ = _extract_const_let_var(content, scan, exclude=arrow_names)

        symbols = _build_symbols(
            modules, classes, functions, interfaces, type_aliases, enums, consts, lets, vars_
        )
        exports = _build_exports(
            content,
            scan,
            lines,
            classes,
            functions,
            interfaces,
            type_aliases,
            enums,
            consts,
            lets,
            vars_,
        )

        return ParseResult.ok(
            relative_path=relative_path,
            language=SourceLanguage.TYPESCRIPT,
            metadata=metadata,
            modules=modules,
            classes=classes,
            functions=functions,
            imports=imports,
            exports=exports,
            symbols=symbols,
        )


def _extract_namespaces(content: str, scan: str, lines: list[str]) -> tuple[ParsedModule, ...]:
    """Collect every `namespace`/`module` block declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        lines: `content` split into lines (accepted for signature consistency with other
            extraction steps; not used here).

    Returns:
        Every declared namespace, in source order.
    """
    del lines
    return tuple(
        ParsedModule(name=match["name"], line_number=line_number_at(content, match.start()))
        for match in _NAMESPACE_PATTERN.finditer(scan)
    )


def _extract_imports(content: str, scan: str) -> tuple[ParsedImport, ...]:
    """Collect every ES module `import` declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        Every import found, in source order.
    """
    imports: list[ParsedImport] = []
    for match in _IMPORT_PATTERN.finditer(scan):
        path = match["path"]
        line = line_number_at(content, match.start())
        is_relative = path.startswith((".", "/"))

        if match["default"]:
            imports.append(
                ParsedImport(
                    module=path, alias=match["default"], is_relative=is_relative, line_number=line
                )
            )
        if match["namespace"]:
            imports.append(
                ParsedImport(
                    module=path,
                    imported_names=("*",),
                    alias=match["namespace"],
                    is_relative=is_relative,
                    line_number=line,
                )
            )
        if match["named"] is not None:
            names: list[str] = []
            aliases: list[str | None] = []
            for item in split_top_level(match["named"]):
                if " as " in item:
                    original, alias = (part.strip() for part in item.split(" as ", 1))
                else:
                    original, alias = item.strip(), None
                if original:
                    names.append(original)
                    aliases.append(alias)
            if len(names) == 1:
                imports.append(
                    ParsedImport(
                        module=path,
                        imported_names=(names[0],),
                        alias=aliases[0],
                        is_relative=is_relative,
                        line_number=line,
                    )
                )
            else:
                for name, alias in zip(names, aliases, strict=True):
                    imports.append(
                        ParsedImport(
                            module=path,
                            imported_names=(name,),
                            alias=alias,
                            is_relative=is_relative,
                            line_number=line,
                        )
                    )
        if not match["default"] and not match["namespace"] and match["named"] is None:
            imports.append(ParsedImport(module=path, is_relative=is_relative, line_number=line))

    return tuple(imports)


def _extract_classes(
    content: str, scan: str, lines: list[str]
) -> tuple[tuple[ParsedClass, ...], tuple[tuple[int, int], ...]]:
    """Collect every `class` declaration and its methods.

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
        spans.append((open_index + 1, close_index))

        base_classes: list[str] = []
        if match["extends"]:
            base_classes.append(match["extends"])
        if match["implements"]:
            base_classes.extend(split_top_level(match["implements"]))

        methods = tuple(
            _build_method(content, scan, method_match)
            for method_match in _METHOD_PATTERN.finditer(scan, open_index + 1, close_index)
            if is_top_level_of_span(scan, open_index + 1, method_match.start())
        )

        line = line_number_at(content, match.start())
        classes.append(
            ParsedClass(
                name=match["name"],
                base_classes=tuple(base_classes),
                methods=methods,
                docstring=_leading_jsdoc(lines, line),
                line_number=line,
            )
        )

    return tuple(classes), tuple(spans)


def _build_method(content: str, scan: str, match: re.Match[str]) -> ParsedFunction:
    """Build a `ParsedFunction` for one method found inside a class body.

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
    return_type = _return_type_after(scan, content, params_close)
    return ParsedFunction(
        name=match["name"],
        parameters=parameters,
        return_type=return_type,
        is_async="async" in scan[match.start() : match.start("name")],
        is_method=True,
        line_number=line_number_at(content, match.start()),
    )


def _return_type_after(scan: str, content: str, params_close: int) -> str | None:
    """Extract a `: ReturnType` annotation immediately following a parameter list.

    Args:
        scan: `content` with comments blanked out.
        content: The original, unmodified file content.
        params_close: Index of the parameter list's closing `)`.

    Returns:
        The return type as written, or None if no `: ReturnType` annotation is present.
    """
    terminator = _next_of(scan, params_close + 1, "{;=")
    text = content[params_close + 1 : terminator].strip()
    if text.startswith(":"):
        return text[1:].strip() or None
    return None


def _next_of(scan: str, start: int, characters: str) -> int:
    """Find the index of the next character in `characters` at or after `start`.

    Args:
        scan: `content` with comments blanked out.
        start: Index to begin searching from.
        characters: Set of characters to stop at.

    Returns:
        The index of the first matching character, or `len(scan)` if none is found.
    """
    for index in range(start, len(scan)):
        if scan[index] in characters:
            return index
    return len(scan)


def _extract_functions(
    content: str,
    scan: str,
    lines: list[str],
    class_spans: tuple[tuple[int, int], ...],
) -> tuple[ParsedFunction, ...]:
    """Collect every top-level `function` declaration and `const`/`let` arrow function.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        lines: `content` split into lines.
        class_spans: Class body spans already found by `_extract_classes`, to exclude methods.

    Returns:
        Every free function found, in source order.
    """
    functions: list[ParsedFunction] = []

    for match in _FUNCTION_PATTERN.finditer(scan):
        if _inside_any(match.start(), class_spans):
            continue
        params_open = scan.find("(", match.end())
        params_close = find_matching_paren(scan, params_open)
        parameters = split_top_level(content[params_open + 1 : params_close])
        return_type = _return_type_after(scan, content, params_close)
        line = line_number_at(content, match.start())
        functions.append(
            ParsedFunction(
                name=match["name"],
                parameters=parameters,
                return_type=return_type,
                is_async=match["async"] is not None,
                docstring=_leading_jsdoc(lines, line),
                line_number=line,
            )
        )

    for match in _ARROW_PATTERN.finditer(scan):
        if _inside_any(match.start(), class_spans) or not _is_arrow(scan, match):
            continue
        params_open = match.end() - 1
        params_close = find_matching_paren(scan, params_open)
        parameters = split_top_level(content[params_open + 1 : params_close])
        return_type = _return_type_after(scan, content, params_close)
        line = line_number_at(content, match.start())
        functions.append(
            ParsedFunction(
                name=match["name"],
                parameters=parameters,
                return_type=return_type,
                is_async=match["async"] is not None,
                docstring=_leading_jsdoc(lines, line),
                line_number=line,
            )
        )

    return tuple(functions)


def _is_arrow(scan: str, match: re.Match[str]) -> bool:
    """Confirm that an `_ARROW_PATTERN` match is really an arrow function, not a plain call.

    `_ARROW_PATTERN` matches the prefix of both `const f = (x) => ...` and `const f = someCall(x);`
    -- only inspecting what follows the parameter list's closing `)` tells them apart.

    Args:
        scan: `content` with comments blanked out.
        match: An `_ARROW_PATTERN` match.

    Returns:
        True if `=>` appears immediately after the parameter list (with only a possible
        `: ReturnType` annotation in between).
    """
    params_open = match.end() - 1
    params_close = find_matching_paren(scan, params_open)
    window = scan[params_close + 1 : params_close + 300]
    arrow_index = window.find("=>")
    if arrow_index == -1:
        return False
    stop_index = min((i for i in (window.find(";"), window.find("\n")) if i != -1), default=-1)
    return stop_index == -1 or arrow_index < stop_index


def _inside_any(index: int, spans: tuple[tuple[int, int], ...]) -> bool:
    """Report whether `index` falls inside any of `spans`.

    Args:
        index: A character offset into `scan`.
        spans: `(start, end)` spans to check against.

    Returns:
        True if `index` falls inside at least one span.
    """
    return any(start <= index < end for start, end in spans)


def _extract_simple(content: str, scan: str, pattern: re.Pattern[str]) -> dict[str, int]:
    """Collect every match of a single-capture-group declaration pattern.

    Shared by the `interface`, `type`, and `enum` extraction steps.

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


def _extract_const_let_var(
    content: str, scan: str, *, exclude: set[str]
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Collect every top-level `const`/`let`/`var` declaration's name and line number.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        exclude: Names already accounted for as arrow functions.

    Returns:
        A triple of `(consts, lets, vars_)` mappings, each from name to 1-indexed line.
    """
    consts: dict[str, int] = {}
    lets: dict[str, int] = {}
    vars_: dict[str, int] = {}
    targets = {"const": consts, "let": lets, "var": vars_}
    for match in _CONST_LET_VAR_NAME_PATTERN.finditer(scan):
        if match["name"] in exclude:
            continue
        targets[match["keyword"]][match["name"]] = line_number_at(content, match.start())
    return consts, lets, vars_


def _leading_jsdoc(lines: list[str], declaration_line: int) -> str | None:
    """Collect a `/** ... */` JSDoc block immediately above a declaration.

    Args:
        lines: The file's content, split into lines.
        declaration_line: 1-indexed line number of the declaration.

    Returns:
        The JSDoc block's text, with comment markers and leading `*` stripped from each line, or
        None if no such block immediately precedes `declaration_line`.
    """
    end = declaration_line - 2  # 0-indexed line directly above the declaration
    if end < 0 or not lines[end].strip().endswith("*/"):
        return None

    start = end
    while start >= 0 and not lines[start].strip().startswith("/**"):
        start -= 1
    if start < 0:
        return None

    block_lines: list[str] = []
    for index in range(start, end + 1):
        text = lines[index].strip().removeprefix("/**").removesuffix("*/").strip()
        text = text.removeprefix("*").strip()
        if text:
            block_lines.append(text)
    return "\n".join(block_lines) if block_lines else None


def _build_symbols(
    modules: tuple[ParsedModule, ...],
    classes: tuple[ParsedClass, ...],
    functions: tuple[ParsedFunction, ...],
    interfaces: dict[str, int],
    type_aliases: dict[str, int],
    enums: dict[str, int],
    consts: dict[str, int],
    lets: dict[str, int],
    vars_: dict[str, int],
) -> tuple[ParsedSymbol, ...]:
    """Build the flat symbol table from every already-extracted construct.

    Args:
        modules: Namespaces already extracted.
        classes: Classes already extracted.
        functions: Free functions already extracted.
        interfaces: Interface names and line numbers.
        type_aliases: Type alias names and line numbers.
        enums: Enum names and line numbers.
        consts: Top-level `const` names and line numbers.
        lets: Top-level `let` names and line numbers.
        vars_: Top-level `var` names and line numbers.

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
        ParsedSymbol(name=name, kind=SymbolKind.INTERFACE, line_number=line)
        for name, line in interfaces.items()
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.TYPE_ALIAS, line_number=line)
        for name, line in type_aliases.items()
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.ENUM, line_number=line)
        for name, line in enums.items()
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.CONSTANT, line_number=line)
        for name, line in consts.items()
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.VARIABLE, line_number=line)
        for name, line in {**lets, **vars_}.items()
    )
    return tuple(symbols)


def _build_exports(
    content: str,
    scan: str,
    lines: list[str],
    classes: tuple[ParsedClass, ...],
    functions: tuple[ParsedFunction, ...],
    interfaces: dict[str, int],
    type_aliases: dict[str, int],
    enums: dict[str, int],
    consts: dict[str, int],
    lets: dict[str, int],
    vars_: dict[str, int],
) -> tuple[ParsedExport, ...]:
    """Build the export list from every `export`-marked declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        lines: `content` split into lines.
        classes: Classes already extracted.
        functions: Free functions already extracted.
        interfaces: Interface names and line numbers.
        type_aliases: Type alias names and line numbers.
        enums: Enum names and line numbers.
        consts: Top-level `const` names and line numbers.
        lets: Top-level `let` names and line numbers.
        vars_: Top-level `var` names and line numbers.

    Returns:
        One `ParsedExport` per exported name: every directly `export`-marked declaration, every
        entry in an `export { ... }` list, one `"*"` per `export * from ...`, and `"default"`
        for an anonymous or expression `export default`.
    """
    candidates: dict[str, int] = {cls.name: cls.line_number for cls in classes}
    candidates.update({function.name: function.line_number for function in functions})
    candidates.update(interfaces)
    candidates.update(type_aliases)
    candidates.update(enums)
    candidates.update(consts)
    candidates.update(lets)
    candidates.update(vars_)

    exports: list[ParsedExport] = [
        ParsedExport(name=name, line_number=line)
        for name, line in candidates.items()
        if lines[line - 1].lstrip().startswith("export")
    ]

    for match in _EXPORT_BRACE_PATTERN.finditer(scan):
        line = line_number_at(content, match.start())
        for item in split_top_level(match["body"]):
            name = item.split(" as ", 1)[1].strip() if " as " in item else item.strip()
            if name:
                exports.append(ParsedExport(name=name, line_number=line))

    for match in _EXPORT_STAR_PATTERN.finditer(scan):
        line = line_number_at(content, match.start())
        exports.append(ParsedExport(name=match["alias"] or "*", line_number=line))

    for match in _EXPORT_DEFAULT_PATTERN.finditer(scan):
        if _NAMED_DEFAULT_PATTERN.match(scan, match.start()) is None:
            exports.append(
                ParsedExport(name="default", line_number=line_number_at(content, match.start()))
            )

    return tuple(exports)
