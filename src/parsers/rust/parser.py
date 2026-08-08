"""`Parser` implementation for Rust source files.

Rust has no `class` keyword, so `struct` declarations play that role here: a `ParsedClass` per
`struct`, with its methods gathered from any `impl StructName { ... }` or
`impl SomeTrait for StructName { ... }` block whose target type matches, and `base_classes`
populated from the trait named in any such `impl ... for StructName` block. `trait` declarations
are reported as `SymbolKind.TRAIT` symbols instead of `ParsedClass` entries, since a trait's own
body holds method *signatures*, not the struct's actual method bodies. "Exported," per this
package's convention of reusing each language's own visibility mechanism, means `pub`.
"""

import re
from collections.abc import Iterator

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
    leading_comment_lines,
    line_number_at,
    require_relative_path,
    split_top_level,
    strip_c_style_comments,
)

#: File extensions `RustParser.supports` recognizes.
_EXTENSIONS = (".rs",)

#: Optional leading `pub`/`pub(...)` visibility modifier, shared by most declaration patterns.
_VIS = r"(?:pub(?:\([^)]*\))?\s+)?"

_MOD_PATTERN = re.compile(rf"^[ \t]*{_VIS}mod\s+(?P<name>\w+)\s*[;{{]", re.MULTILINE)
_USE_PATTERN = re.compile(rf"^[ \t]*{_VIS}use\s+(?P<body>[^;]+);", re.MULTILINE | re.DOTALL)
_IMPL_PATTERN = re.compile(
    r"^[ \t]*impl(?:<[^>]*>)?\s+"
    r"(?:(?P<trait>[\w:]+(?:<[^>]*>)?)\s+for\s+)?"
    r"(?P<type>\w+)(?:<[^>]*>)?\s*(?:where[^{]*)?\{",
    re.MULTILINE,
)
_TRAIT_PATTERN = re.compile(
    rf"^[ \t]*{_VIS}(?:unsafe\s+)?trait\s+(?P<name>\w+)(?:<[^>]*>)?"
    r"(?:\s*:\s*[^{;]+?)?\s*\{",
    re.MULTILINE,
)
_ENUM_PATTERN = re.compile(rf"^[ \t]*{_VIS}enum\s+(?P<name>\w+)", re.MULTILINE)
_TYPE_ALIAS_PATTERN = re.compile(rf"^[ \t]*{_VIS}type\s+(?P<name>\w+)", re.MULTILINE)
_CONST_STATIC_PATTERN = re.compile(
    rf"^[ \t]*{_VIS}(?:const|static)\s+(?:mut\s+)?(?P<name>\w+)\s*:", re.MULTILINE
)
_STRUCT_PATTERN = re.compile(
    rf"^[ \t]*{_VIS}struct\s+(?P<name>\w+)(?:<[^>]*>)?\s*(?P<form>[{{(;])", re.MULTILINE
)
_FN_PATTERN = re.compile(
    rf"^[ \t]*{_VIS}(?P<async>async\s+)?(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?"
    r"fn\s+(?P<name>\w+)(?:<[^>]*>)?\s*\(",
    re.MULTILINE,
)


class RustParser(Parser):
    """Extracts modules, classes, functions, imports, exports, and symbols from Rust source."""

    @property
    def language(self) -> SourceLanguage:
        """The language this parser produces `ParseResult` entries for.

        Returns:
            `SourceLanguage.RUST`.
        """
        return SourceLanguage.RUST

    def supports(self, relative_path: str) -> bool:
        """Report whether `relative_path` has the Rust extension.

        Args:
            relative_path: Path of the candidate file.

        Returns:
            True if `relative_path` ends with `.rs`.
        """
        return has_extension(relative_path, _EXTENSIONS)

    def parse(self, *, relative_path: str, content: str) -> ParseResult:
        """Parse Rust `content` into a `ParseResult`.

        Args:
            relative_path: Path of the file `content` was read from.
            content: The file's full text content.

        Returns:
            A successful result. This lightweight scan does not itself validate Rust's grammar,
            so this parser has no failure path of its own.

        Raises:
            ValidationError: If `relative_path` is blank.
        """
        require_relative_path(relative_path)
        scan = strip_c_style_comments(content)
        lines = content.splitlines()
        metadata = build_file_metadata(
            relative_path=relative_path, language=SourceLanguage.RUST, content=content
        )

        modules = _extract_modules(content, scan, lines)
        imports = _extract_imports(content, scan)
        struct_forms = _extract_struct_forms(content, scan)
        impl_blocks = _extract_impl_blocks(scan)
        trait_spans = _extract_trait_spans(scan)
        traits = _extract_simple(content, scan, _TRAIT_PATTERN, lines=lines)
        enums = _extract_simple(content, scan, _ENUM_PATTERN, lines=lines)
        type_aliases = _extract_simple(content, scan, _TYPE_ALIAS_PATTERN, lines=lines)
        consts_statics = _extract_simple(content, scan, _CONST_STATIC_PATTERN, lines=lines)

        struct_line_by_name = {name: line for name, line, _form in struct_forms}
        base_classes_by_struct = _base_classes_by_struct(impl_blocks)
        functions, methods_by_struct, all_methods = _extract_functions(
            content, scan, lines, impl_blocks, trait_spans, struct_line_by_name
        )

        classes = tuple(
            ParsedClass(
                name=name,
                base_classes=tuple(base_classes_by_struct.get(name, ())),
                methods=tuple(methods_by_struct.get(name, ())),
                docstring=leading_comment_lines(lines, line, prefix="///"),
                line_number=line,
            )
            for name, line, _form in struct_forms
        )

        symbols = _build_symbols(
            modules, classes, traits, enums, type_aliases, functions, all_methods, consts_statics
        )
        exports = _build_exports(
            lines, struct_forms, traits, enums, type_aliases, consts_statics, functions
        )

        return ParseResult.ok(
            relative_path=relative_path,
            language=SourceLanguage.RUST,
            metadata=metadata,
            modules=modules,
            classes=classes,
            functions=functions,
            imports=imports,
            exports=exports,
            symbols=symbols,
        )


def _extract_modules(content: str, scan: str, lines: list[str]) -> tuple[ParsedModule, ...]:
    """Collect every `mod name;`/`mod name { ... }` declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        lines: `content` split into lines.

    Returns:
        Every declared module, in source order.
    """
    return tuple(
        ParsedModule(name=match["name"], line_number=line_number_at(content, match.start()))
        for match in _MOD_PATTERN.finditer(scan)
    )


def _extract_imports(content: str, scan: str) -> tuple[ParsedImport, ...]:
    """Collect every `use` declaration, including brace-grouped forms.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        Every import found, in source order.
    """
    imports: list[ParsedImport] = []
    for match in _USE_PATTERN.finditer(scan):
        line = line_number_at(content, match.start())
        imports.extend(_parse_use_body(match["body"].strip(), line_number=line))
    return tuple(imports)


def _parse_use_body(body: str, *, line_number: int) -> Iterator[ParsedImport]:
    """Parse the path expression of a single `use` statement into one or more imports.

    Args:
        body: The text between `use` and its terminating `;`.
        line_number: 1-indexed line the `use` statement starts on.

    Yields:
        One `ParsedImport` per name the statement brings into scope.
    """
    body = " ".join(body.split())
    is_relative = body.startswith(("crate::", "self::", "super::"))
    brace_index = body.find("{")

    if brace_index != -1 and body.rstrip().endswith("}"):
        prefix = body[:brace_index].strip().removesuffix("::").strip()
        close_index = find_matching_brace(body, brace_index)
        for item in split_top_level(body[brace_index + 1 : close_index]):
            yield _build_use_import(prefix, item, is_relative=is_relative, line_number=line_number)
        return

    yield _build_use_import("", body, is_relative=is_relative, line_number=line_number)


def _build_use_import(
    prefix: str, item: str, *, is_relative: bool, line_number: int
) -> ParsedImport:
    """Build one `ParsedImport` from a single grouped or ungrouped `use` path entry.

    Args:
        prefix: The path shared by every entry in the same brace group, or `""` for an ungrouped
            `use` statement, in which case `item` is the statement's entire path.
        item: One entry: a plain name, `self`, `*`, or `name as alias`.
        is_relative: Whether the overall `use` path is `crate`/`self`/`super`-rooted.
        line_number: 1-indexed line the `use` statement starts on.

    Returns:
        The corresponding `ParsedImport`.
    """
    alias: str | None = None
    if " as " in item:
        item, alias = (part.strip() for part in item.split(" as ", 1))

    if item == "*":
        module = prefix if prefix else item
        return ParsedImport(
            module=module, imported_names=("*",), is_relative=is_relative, line_number=line_number
        )
    if item == "self":
        module = prefix if prefix else item
        return ParsedImport(
            module=module,
            imported_names=("self",),
            alias=alias,
            is_relative=is_relative,
            line_number=line_number,
        )
    if prefix:
        return ParsedImport(
            module=prefix,
            imported_names=(item,),
            alias=alias,
            is_relative=is_relative,
            line_number=line_number,
        )
    if "::" in item:
        module, _, name = item.rpartition("::")
        return ParsedImport(
            module=module,
            imported_names=(name,),
            alias=alias,
            is_relative=is_relative,
            line_number=line_number,
        )
    return ParsedImport(module=item, alias=alias, is_relative=is_relative, line_number=line_number)


def _extract_struct_forms(content: str, scan: str) -> tuple[tuple[str, int, str], ...]:
    """Collect every `struct` declaration's name, line number, and syntactic form.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.

    Returns:
        One `(name, line_number, form)` triple per struct, in source order, where `form` is
        `"{"` (field struct), `"("` (tuple struct), or `";"` (unit struct).
    """
    return tuple(
        (match["name"], line_number_at(content, match.start()), match["form"])
        for match in _STRUCT_PATTERN.finditer(scan)
    )


def _extract_impl_blocks(scan: str) -> tuple[tuple[str, str | None, int, int], ...]:
    """Collect every `impl` block's target type, trait (if any), and body span.

    Args:
        scan: `content` with comments blanked out.

    Returns:
        One `(type_name, trait_name, body_start, body_end)` tuple per `impl` block, where
        `body_start`/`body_end` are indices into `scan` (and, since they are the same length,
        into `content` too) spanning from just after the opening `{` to the closing `}`.
    """
    blocks: list[tuple[str, str | None, int, int]] = []
    for match in _IMPL_PATTERN.finditer(scan):
        open_index = match.end() - 1
        close_index = find_matching_brace(scan, open_index)
        blocks.append((match["type"], match["trait"], open_index + 1, close_index))
    return tuple(blocks)


def _extract_trait_spans(scan: str) -> tuple[tuple[int, int], ...]:
    """Collect every `trait` declaration's body span.

    A `trait` body holds method *signatures* rather than a struct's actual method
    implementations, so unlike an `impl` block's span, a trait's span carries no owning struct --
    it exists only so a signature-only `fn ...;` inside it is still recognized as `is_method`
    rather than mistaken for a free function.

    Args:
        scan: `content` with comments blanked out.

    Returns:
        One `(body_start, body_end)` pair per `trait` declaration, spanning from just after the
        opening `{` to the closing `}`.
    """
    spans: list[tuple[int, int]] = []
    for match in _TRAIT_PATTERN.finditer(scan):
        open_index = match.end() - 1
        close_index = find_matching_brace(scan, open_index)
        spans.append((open_index + 1, close_index))
    return tuple(spans)


def _base_classes_by_struct(
    impl_blocks: tuple[tuple[str, str | None, int, int], ...],
) -> dict[str, list[str]]:
    """Group the trait named in each `impl Trait for Type` block by its target type.

    Args:
        impl_blocks: Impl blocks already extracted by `_extract_impl_blocks`.

    Returns:
        A mapping of struct name to every trait it has a trait-`impl` block for, in source
        order.
    """
    bases: dict[str, list[str]] = {}
    for type_name, trait_name, _start, _end in impl_blocks:
        if trait_name is not None:
            bases.setdefault(type_name, []).append(trait_name)
    return bases


def _extract_simple(
    content: str, scan: str, pattern: re.Pattern[str], *, lines: list[str]
) -> dict[str, int]:
    """Collect every match of a single-capture-group declaration pattern.

    Shared by the `trait`, `enum`, `type`, and `const`/`static` extraction steps, which all
    reduce to "find every declaration of this keyword and record its name and line."

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        pattern: A compiled pattern with a `name` capture group.
        lines: `content` split into lines (accepted for a uniform call signature across every
            caller; not used by this particular extraction).

    Returns:
        A mapping of declared name to 1-indexed declaration line, in source order.
    """
    del lines
    return {
        match["name"]: line_number_at(content, match.start()) for match in pattern.finditer(scan)
    }


def _extract_functions(
    content: str,
    scan: str,
    lines: list[str],
    impl_blocks: tuple[tuple[str, str | None, int, int], ...],
    trait_spans: tuple[tuple[int, int], ...],
    struct_line_by_name: dict[str, int],
) -> tuple[tuple[ParsedFunction, ...], dict[str, list[ParsedFunction]], tuple[ParsedFunction, ...]]:
    """Collect every `fn` declaration, splitting free functions from methods.

    A `fn` is a method if it falls inside any `impl` or `trait` block's body span (the latter
    covers signature-only trait methods, which have no body of their own to otherwise mark them
    as anything but a free function). It is attached to a struct's `methods` only when it comes
    from an `impl` block whose target is a known struct -- a trait's signature-only methods, and
    an `impl` block for an unrecognized type, remain unattached. Every other `fn` is a free
    function.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        lines: `content` split into lines.
        impl_blocks: Impl blocks already extracted by `_extract_impl_blocks`.
        trait_spans: Trait body spans already extracted by `_extract_trait_spans`.
        struct_line_by_name: Struct names already found, used to attach a method to its type.

    Returns:
        A triple of: free functions, methods grouped by their struct's name (only for `impl`
        targets matching a known struct), and every method regardless of struct resolution.
    """
    functions: list[ParsedFunction] = []
    methods_by_struct: dict[str, list[ParsedFunction]] = {}
    all_methods: list[ParsedFunction] = []

    for match in _FN_PATTERN.finditer(scan):
        params_open = match.end() - 1
        params_close = find_matching_paren(scan, params_open)
        parameters = split_top_level(content[params_open + 1 : params_close])

        terminator = _next_terminator(scan, params_close + 1)
        return_text = content[params_close + 1 : terminator].strip()
        return_type = _extract_arrow_return(return_text)

        line = line_number_at(content, match.start())
        is_method, owner = _containing_owner(match.start(), impl_blocks, trait_spans)
        function = ParsedFunction(
            name=match["name"],
            parameters=parameters,
            return_type=return_type,
            is_async=match["async"] is not None,
            is_method=is_method,
            docstring=leading_comment_lines(lines, line, prefix="///"),
            line_number=line,
        )

        if not is_method:
            functions.append(function)
        else:
            all_methods.append(function)
            if owner is not None and owner in struct_line_by_name:
                methods_by_struct.setdefault(owner, []).append(function)

    return tuple(functions), methods_by_struct, tuple(all_methods)


def _next_terminator(scan: str, start: int) -> int:
    """Find the index of the next `{` or `;` at or after `start`.

    Used to bound the text that might contain a function's `-> ReturnType`.

    Args:
        scan: `content` with comments blanked out.
        start: Index to begin searching from.

    Returns:
        The index of the next `{` or `;`, or `len(scan)` if neither appears again.
    """
    for index in range(start, len(scan)):
        if scan[index] in "{;":
            return index
    return len(scan)


def _extract_arrow_return(text: str) -> str | None:
    """Pull the `-> ReturnType` portion out of the text following a function's parameter list.

    Args:
        text: Text between a function's closing `)` and its body/terminator.

    Returns:
        The return type as written, or None if `text` has no `->`.
    """
    if "->" not in text:
        return None
    return text.split("->", 1)[1].strip() or None


def _containing_owner(
    index: int,
    impl_blocks: tuple[tuple[str, str | None, int, int], ...],
    trait_spans: tuple[tuple[int, int], ...],
) -> tuple[bool, str | None]:
    """Determine whether `index` is inside a method-defining block, and its owning struct if any.

    Args:
        index: A character offset into `scan`.
        impl_blocks: Impl blocks already extracted by `_extract_impl_blocks`.
        trait_spans: Trait body spans already extracted by `_extract_trait_spans`.

    Returns:
        `(is_method, owner)`. `is_method` is True if `index` falls inside an `impl` or `trait`
        body. `owner` is the innermost enclosing `impl` block's target type name, or None if the
        nearest enclosing container is a `trait` body (no struct to attach to) or `index` is
        outside every container.
    """
    best: tuple[int, str] | None = None
    for type_name, _trait, start, end in impl_blocks:
        if start <= index < end and (best is None or (end - start) < best[0]):
            best = (end - start, type_name)
    if best is not None:
        return True, best[1]
    for start, end in trait_spans:
        if start <= index < end:
            return True, None
    return False, None


def _build_symbols(
    modules: tuple[ParsedModule, ...],
    classes: tuple[ParsedClass, ...],
    traits: dict[str, int],
    enums: dict[str, int],
    type_aliases: dict[str, int],
    functions: tuple[ParsedFunction, ...],
    methods: tuple[ParsedFunction, ...],
    consts_statics: dict[str, int],
) -> tuple[ParsedSymbol, ...]:
    """Build the flat symbol table from every already-extracted construct.

    Args:
        modules: Modules already extracted.
        classes: Structs already extracted.
        traits: Trait names and line numbers.
        enums: Enum names and line numbers.
        type_aliases: Type alias names and line numbers.
        functions: Free functions already extracted.
        methods: Every method already extracted, regardless of struct resolution.
        consts_statics: `const`/`static` names and line numbers.

    Returns:
        One `ParsedSymbol` per construct found.
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
        ParsedSymbol(name=name, kind=SymbolKind.TRAIT, line_number=line)
        for name, line in traits.items()
    )
    symbols.extend(
        ParsedSymbol(name=name, kind=SymbolKind.ENUM, line_number=line)
        for name, line in enums.items()
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
        for name, line in consts_statics.items()
    )
    return tuple(symbols)


def _build_exports(
    lines: list[str],
    struct_forms: tuple[tuple[str, int, str], ...],
    traits: dict[str, int],
    enums: dict[str, int],
    type_aliases: dict[str, int],
    consts_statics: dict[str, int],
    functions: tuple[ParsedFunction, ...],
) -> tuple[ParsedExport, ...]:
    """Build the export list from every top-level declaration marked `pub`.

    Args:
        lines: The original file content, split into lines.
        struct_forms: Structs already extracted.
        traits: Trait names and line numbers.
        enums: Enum names and line numbers.
        type_aliases: Type alias names and line numbers.
        consts_statics: `const`/`static` names and line numbers.
        functions: Free functions already extracted.

    Returns:
        One `ParsedExport` per top-level declaration whose line starts with `pub`.
    """
    candidates: dict[str, int] = {name: line for name, line, _form in struct_forms}
    candidates.update(traits)
    candidates.update(enums)
    candidates.update(type_aliases)
    candidates.update(consts_statics)
    candidates.update({function.name: function.line_number for function in functions})

    return tuple(
        ParsedExport(name=name, line_number=line)
        for name, line in candidates.items()
        if lines[line - 1].lstrip().startswith("pub")
    )
