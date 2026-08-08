"""`Parser` implementation for Go source files.

Go has no exported concept of a base class or trait -- interface satisfaction is structural and
implicit -- so `ParsedClass.base_classes` is always empty here; Go's own inheritance-like
mechanism, struct field embedding, is a field-level detail this file-level structural scan does
not attempt to resolve. "Exported," per Go convention, means a top-level identifier whose name
starts with an uppercase letter; there is no `export` keyword to look for.
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
    find_matching_paren,
    has_extension,
    line_number_at,
    require_relative_path,
    split_top_level,
    strip_c_style_comments,
)

#: File extensions `GoParser.supports` recognizes.
_EXTENSIONS = (".go",)

_PACKAGE_PATTERN = re.compile(r"^[ \t]*package\s+(?P<name>\w+)", re.MULTILINE)
_IMPORT_BLOCK_PATTERN = re.compile(r"import\s*\(\s*(?P<body>.*?)\)", re.DOTALL)
_IMPORT_SINGLE_PATTERN = re.compile(
    r'^[ \t]*import\s+(?:(?P<alias>_|\.|\w+)\s+)?"(?P<path>[^"]+)"', re.MULTILINE
)
_IMPORT_LINE_PATTERN = re.compile(
    r'^[ \t]*(?:(?P<alias>_|\.|\w+)[ \t]+)?"(?P<path>[^"]+)"[ \t]*$', re.MULTILINE
)
_STRUCT_PATTERN = re.compile(
    r"^[ \t]*type\s+(?P<name>\w+)(?:\[[^\]]*\])?\s+struct\s*\{", re.MULTILINE
)
_INTERFACE_PATTERN = re.compile(
    r"^[ \t]*type\s+(?P<name>\w+)(?:\[[^\]]*\])?\s+interface\s*\{", re.MULTILINE
)
_TYPE_ALIAS_PATTERN = re.compile(r"^[ \t]*type\s+(?P<name>\w+)\s*=?\s*[^\n{]+$", re.MULTILINE)
_FUNC_PATTERN = re.compile(
    r"^[ \t]*func\s+"
    r"(?:\(\s*\w*\s*\*?(?P<recv_type>\w+)\s*\)\s+)?"
    r"(?P<name>\w+)(?:\[[^\]]*\])?\s*\(",
    re.MULTILINE,
)
_CONST_VAR_BLOCK_PATTERN = re.compile(
    r"^[ \t]*(?P<keyword>const|var)\s*\(\s*(?P<body>.*?)^[ \t]*\)", re.DOTALL | re.MULTILINE
)
_CONST_VAR_SINGLE_PATTERN = re.compile(
    r"^[ \t]*(?P<keyword>const|var)\s+(?P<name>\w+)", re.MULTILINE
)
_BLOCK_ENTRY_NAME_PATTERN = re.compile(r"^[ \t]*(?P<name>\w+)", re.MULTILINE)


class GoParser(Parser):
    """Extracts modules, classes, functions, imports, exports, and symbols from Go source.

    A file's leading `package` clause becomes its one `ParsedModule`. `type ... struct` becomes
    a `ParsedClass`, with methods gathered from any `func (recv *Name) Method(...)` declarations
    whose receiver type matches. `type ... interface` becomes a `SymbolKind.INTERFACE` symbol,
    not a `ParsedClass`, since an interface has no method bodies of its own.
    """

    @property
    def language(self) -> SourceLanguage:
        """The language this parser produces `ParseResult` entries for.

        Returns:
            `SourceLanguage.GO`.
        """
        return SourceLanguage.GO

    def supports(self, relative_path: str) -> bool:
        """Report whether `relative_path` has the Go extension.

        Args:
            relative_path: Path of the candidate file.

        Returns:
            True if `relative_path` ends with `.go`.
        """
        return has_extension(relative_path, _EXTENSIONS)

    def parse(self, *, relative_path: str, content: str) -> ParseResult:
        """Parse Go `content` into a `ParseResult`.

        Args:
            relative_path: Path of the file `content` was read from.
            content: The file's full text content.

        Returns:
            A successful result. Go's grammar is simple enough that this lightweight scan does
            not itself detect malformed input, so this parser has no failure path of its own.

        Raises:
            ValidationError: If `relative_path` is blank.
        """
        require_relative_path(relative_path)
        scan = strip_c_style_comments(content)
        metadata = build_file_metadata(
            relative_path=relative_path, language=SourceLanguage.GO, content=content
        )

        modules = _extract_package(content, scan)
        imports = _extract_imports(content, scan)
        structs = _extract_struct_names(content, scan)
        interfaces = _extract_interface_names(content, scan)
        type_aliases = _extract_type_aliases(content, scan, exclude=set(structs) | set(interfaces))
        consts, vars_ = _extract_const_var_names(content, scan)
        functions, methods_by_struct, all_methods = _extract_functions(content, scan, structs)

        classes = tuple(
            ParsedClass(name=name, methods=tuple(methods_by_struct.get(name, ())), line_number=line)
            for name, line in structs.items()
        )

        symbols = _build_symbols(
            modules, classes, interfaces, type_aliases, functions, all_methods, consts, vars_
        )
        exports = _build_exports(structs, interfaces, type_aliases, functions, consts, vars_)

        return ParseResult.ok(
            relative_path=relative_path,
            language=SourceLanguage.GO,
            metadata=metadata,
            modules=modules,
            classes=classes,
            functions=functions,
            imports=imports,
            exports=exports,
            symbols=symbols,
        )


def _extract_package(content: str, scan: str) -> tuple[ParsedModule, ...]:
    """Collect the file's `package` clause, if present.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        A single-element tuple with the declared package, or an empty tuple if none is found.
    """
    match = _PACKAGE_PATTERN.search(scan)
    if match is None:
        return ()
    return (ParsedModule(name=match["name"], line_number=line_number_at(content, match.start())),)


def _extract_imports(content: str, scan: str) -> tuple[ParsedImport, ...]:
    """Collect every grouped and single-line `import` declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        Every import found, in source order.
    """
    imports: list[ParsedImport] = []
    covered: list[tuple[int, int]] = []

    for block in _IMPORT_BLOCK_PATTERN.finditer(scan):
        covered.append(block.span())
        body_start = block.start("body")
        for line in _IMPORT_LINE_PATTERN.finditer(block["body"]):
            alias = line["alias"]
            imports.append(
                ParsedImport(
                    module=line["path"],
                    alias=None if alias in (None, "_", ".") else alias,
                    is_relative=line["path"].startswith("."),
                    line_number=line_number_at(content, body_start + line.start()),
                )
            )

    for single in _IMPORT_SINGLE_PATTERN.finditer(scan):
        if any(start <= single.start() < end for start, end in covered):
            continue
        alias = single["alias"]
        imports.append(
            ParsedImport(
                module=single["path"],
                alias=None if alias in (None, "_", ".") else alias,
                is_relative=single["path"].startswith("."),
                line_number=line_number_at(content, single.start()),
            )
        )

    return tuple(imports)


def _extract_struct_names(content: str, scan: str) -> dict[str, int]:
    """Collect every `type ... struct` declaration's name and line number.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        A mapping of struct name to 1-indexed declaration line, in source order.
    """
    return {
        match["name"]: line_number_at(content, match.start())
        for match in _STRUCT_PATTERN.finditer(scan)
    }


def _extract_interface_names(content: str, scan: str) -> dict[str, int]:
    """Collect every `type ... interface` declaration's name and line number.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        A mapping of interface name to 1-indexed declaration line, in source order.
    """
    return {
        match["name"]: line_number_at(content, match.start())
        for match in _INTERFACE_PATTERN.finditer(scan)
    }


def _extract_type_aliases(content: str, scan: str, *, exclude: set[str]) -> dict[str, int]:
    """Collect every other `type` declaration (aliases and defined types).

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        exclude: Names already accounted for as a struct or interface, to skip re-matching their
            own `type ... struct`/`type ... interface` header line.

    Returns:
        A mapping of type name to 1-indexed declaration line, in source order.
    """
    aliases: dict[str, int] = {}
    for match in _TYPE_ALIAS_PATTERN.finditer(scan):
        name = match["name"]
        if name in exclude:
            continue
        aliases[name] = line_number_at(content, match.start())
    return aliases


def _extract_const_var_names(content: str, scan: str) -> tuple[dict[str, int], dict[str, int]]:
    """Collect every top-level `const` and `var` declaration's name and line number.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        A pair of `(consts, vars_)` mappings, each from name to 1-indexed declaration line.
    """
    consts: dict[str, int] = {}
    vars_: dict[str, int] = {}
    covered: list[tuple[int, int]] = []

    for block in _CONST_VAR_BLOCK_PATTERN.finditer(scan):
        covered.append(block.span())
        target = consts if block["keyword"] == "const" else vars_
        body_start = block.start("body")
        for entry in _BLOCK_ENTRY_NAME_PATTERN.finditer(block["body"]):
            if entry["name"] == "_":
                continue
            target[entry["name"]] = line_number_at(content, body_start + entry.start())

    for single in _CONST_VAR_SINGLE_PATTERN.finditer(scan):
        if any(start <= single.start() < end for start, end in covered):
            continue
        target = consts if single["keyword"] == "const" else vars_
        target[single["name"]] = line_number_at(content, single.start())

    return consts, vars_


def _extract_functions(
    content: str, scan: str, structs: dict[str, int]
) -> tuple[tuple[ParsedFunction, ...], dict[str, list[ParsedFunction]], tuple[ParsedFunction, ...]]:
    """Collect every top-level function and method declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        structs: Struct names already found, used to attach a method to its receiver type.

    Returns:
        A triple of: free functions (no receiver), methods grouped by their receiver struct's
        name (only for receivers matching a known struct), and every method regardless of
        whether its receiver matched a known struct.
    """
    functions: list[ParsedFunction] = []
    methods_by_struct: dict[str, list[ParsedFunction]] = {}
    all_methods: list[ParsedFunction] = []

    for match in _FUNC_PATTERN.finditer(scan):
        params_open = match.end() - 1
        params_close = find_matching_paren(scan, params_open)
        parameters = split_top_level(content[params_open + 1 : params_close])

        brace_index = scan.find("{", params_close + 1)
        return_text = content[params_close + 1 : brace_index].strip() if brace_index != -1 else ""

        recv_type = match["recv_type"]
        function = ParsedFunction(
            name=match["name"],
            parameters=parameters,
            return_type=return_text or None,
            is_method=recv_type is not None,
            line_number=line_number_at(content, match.start()),
        )

        if recv_type is None:
            functions.append(function)
        else:
            all_methods.append(function)
            if recv_type in structs:
                methods_by_struct.setdefault(recv_type, []).append(function)

    return tuple(functions), methods_by_struct, tuple(all_methods)


def _build_symbols(
    modules: tuple[ParsedModule, ...],
    classes: tuple[ParsedClass, ...],
    interfaces: dict[str, int],
    type_aliases: dict[str, int],
    functions: tuple[ParsedFunction, ...],
    methods: tuple[ParsedFunction, ...],
    consts: dict[str, int],
    vars_: dict[str, int],
) -> tuple[ParsedSymbol, ...]:
    """Build the flat symbol table from every already-extracted construct.

    Args:
        modules: The file's package clause, as a `ParsedModule`, if any.
        classes: Structs already extracted.
        interfaces: Interface names and line numbers.
        type_aliases: Other type names and line numbers.
        functions: Free functions already extracted.
        methods: Every method already extracted, regardless of receiver resolution.
        consts: Top-level `const` names and line numbers.
        vars_: Top-level `var` names and line numbers.

    Returns:
        One `ParsedSymbol` per construct found, package first.
    """
    symbols: list[ParsedSymbol] = [
        ParsedSymbol(name=module.name, kind=SymbolKind.MODULE, line_number=module.line_number)
        for module in modules
    ]
    symbols.extend(
        ParsedSymbol(name=cls.name, kind=SymbolKind.STRUCT, line_number=cls.line_number)
        for cls in classes
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
        ParsedSymbol(name=function.name, kind=SymbolKind.FUNCTION, line_number=function.line_number)
        for function in functions
    )
    symbols.extend(
        ParsedSymbol(name=method.name, kind=SymbolKind.METHOD, line_number=method.line_number)
        for method in methods
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.CONSTANT, line_number=line)
        for name, line in consts.items()
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.VARIABLE, line_number=line)
        for name, line in vars_.items()
    )
    return tuple(symbols)


def _build_exports(
    structs: dict[str, int],
    interfaces: dict[str, int],
    type_aliases: dict[str, int],
    functions: tuple[ParsedFunction, ...],
    consts: dict[str, int],
    vars_: dict[str, int],
) -> tuple[ParsedExport, ...]:
    """Build the export list from every top-level, capitalized name.

    Args:
        structs: Struct names and line numbers.
        interfaces: Interface names and line numbers.
        type_aliases: Other type names and line numbers.
        functions: Free functions already extracted.
        consts: Top-level `const` names and line numbers.
        vars_: Top-level `var` names and line numbers.

    Returns:
        One `ParsedExport` per top-level name starting with an uppercase letter.
    """
    candidates: dict[str, int] = {**structs, **interfaces, **type_aliases, **consts, **vars_}
    candidates.update({function.name: function.line_number for function in functions})
    return tuple(
        ParsedExport(name=name, line_number=line)
        for name, line in candidates.items()
        if name[:1].isupper()
    )
