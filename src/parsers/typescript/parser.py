"""`Parser` implementation for TypeScript source files.

`interface` declarations are reported as `ParsedInterface` entries, with method signatures
stored separately from class methods and data properties stored as `ParsedProperty` entries. They
also appear as `SymbolKind.INTERFACE` symbols, with their properties as `SymbolKind.PROPERTY`
symbols.
`class` is reported as a `ParsedClass`, with `base_classes`
combining whatever the class both `extends` and `implements`, since `ParsedClass` does not
distinguish the two relationships.

The scope scan treats namespace/module blocks as transparent and other brace blocks as opaque.
Declarations nested in function bodies, callbacks, class bodies, and other executable/type scopes
are excluded from the flat file-scope tables. The parser remains a lightweight regular-expression
scan rather than a full TypeScript lexer.

Comments and literals are classified by a single lexical pass, `_lex_typescript`. Its comment
half is `strip_typescript_comments` -- unlike the shared `strip_c_style_comments`, it recognizes
quoted strings, template literals, and heuristically detected regular-expression literals, so
comment markers inside them are left alone. Its literal half is the mask used for brace-depth
analysis. Both halves come from the same result, so they cannot disagree about where a literal
ends. Template literals are tracked to any nesting depth: a `${...}` expression is code, and
strings, comments, and further templates inside it are handled in turn. JSX in TSX files is
handled by a lightweight tag/text state machine, not a full JSX parser. Regular-expression versus
division classification remains heuristic and can be ambiguous in uncommon expression contexts.
"""

import re
from collections.abc import Sequence

from src.domain.entities import SourceLanguage

from ..base import (
    ParsedClass,
    ParsedExport,
    ParsedFunction,
    ParsedImport,
    ParsedInterface,
    ParsedModule,
    ParsedProperty,
    ParsedSymbol,
    Parser,
    ParseResult,
    SymbolKind,
    build_file_metadata,
    find_matching_brace,
    find_matching_paren,
    has_extension,
    line_number_at,
    require_relative_path,
    split_top_level,
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
    rf"^[ \t]*{_EXPORT}(?:declare\s+)?(?:namespace|module)\s+"
    r"(?P<name>[\w$.]+|[\"\'][^\"\']+[\"\'])\s*\{",
    re.MULTILINE,
)
_GLOBAL_AUGMENTATION_PATTERN = re.compile(r"^[ \t]*declare\s+global\s*\{", re.MULTILINE)
_CLASS_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:declare\s+)?(?:abstract\s+)?class\s+(?P<name>[\w$]+)",
    re.MULTILINE,
)
_METHOD_PATTERN = re.compile(
    r"(?<![\w$])(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:readonly\s+)?"
    r"(?:abstract\s+)?(?:async\s+)?(?:get\s+|set\s+)?(?:\*\s*)?"
    r"(?P<name>[\w$]+)\??\s*(?:<[^;\n{}]*>)?\s*\(",
    re.MULTILINE,
)
_INTERFACE_PATTERN = re.compile(rf"^[ \t]*{_EXPORT}interface\s+(?P<name>[\w$]+)", re.MULTILINE)
_TYPE_ALIAS_PATTERN = re.compile(rf"^[ \t]*{_EXPORT}type\s+(?P<name>[\w$]+)", re.MULTILINE)
_ENUM_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:declare\s+)?(?:const\s+)?enum\s+(?P<name>[\w$]+)",
    re.MULTILINE,
)
_FUNCTION_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:declare\s+)?(?P<async>async\s+)?function\s*\*?\s+(?P<name>[\w$]+)",
    re.MULTILINE,
)
_ARROW_PATTERN = re.compile(
    rf"^[ \t]*{_EXPORT}(?:const|let)\s+(?P<name>[\w$]+)\s*(?::[^=]+?)?=\s*(?P<async>async\s+)?"
    r"(?:<[^;{}]*?>\s*)?\(",
    re.MULTILINE,
)
_CONST_LET_VAR_NAME_PATTERN = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?P<keyword>const|let|var)\s+(?!enum\b)(?P<name>[\w$]+)",
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
        scan, structural_scan = _scan_typescript(
            content, allow_jsx=relative_path.lower().endswith(".tsx")
        )
        lines = content.splitlines()
        metadata = build_file_metadata(
            relative_path=relative_path, language=SourceLanguage.TYPESCRIPT, content=content
        )

        namespace_opens = {
            match.end() - 1 for match in _NAMESPACE_PATTERN.finditer(scan)
        }
        namespace_opens.update(
            match.end() - 1 for match in _GLOBAL_AUGMENTATION_PATTERN.finditer(structural_scan)
        )
        opaque_depths = _compute_opaque_depths(structural_scan, namespace_opens)
        modules = _extract_namespaces(content, scan, lines, opaque_depths)
        imports = _extract_imports(content, scan)
        classes, class_spans = _extract_classes(
            content, scan, structural_scan, lines, opaque_depths
        )
        arrow_names = {
            match["name"]
            for match in _ARROW_PATTERN.finditer(scan)
            if opaque_depths[match.start()] == 0 and _is_arrow(structural_scan, match)
        }
        functions = _extract_functions(
            content, scan, structural_scan, lines, class_spans, opaque_depths
        )
        interface_declarations = _extract_interfaces(
            content, scan, structural_scan, opaque_depths
        )
        interfaces = {item.name: item.line_number for item in interface_declarations}
        type_aliases = _extract_simple(content, scan, _TYPE_ALIAS_PATTERN, opaque_depths)
        enums = _extract_simple(content, scan, _ENUM_PATTERN, opaque_depths)
        consts, lets, vars_ = _extract_const_let_var(
            content, scan, exclude=arrow_names, opaque_depths=opaque_depths
        )

        symbols = _build_symbols(
            modules, classes, functions, interfaces, type_aliases, enums, consts, lets, vars_,
            interface_declarations,
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
            interfaces=interface_declarations,
            functions=functions,
            imports=imports,
            exports=exports,
            symbols=symbols,
        )


def strip_typescript_comments(content: str, *, allow_jsx: bool = False) -> str:
    """Blank out `//` and `/* ... */` comments in TypeScript `content`, leaving literals intact.

    A TypeScript-aware replacement for the shared `strip_c_style_comments`, which does not
    recognize string literals and therefore truncates text such as `"http://example.com"` or
    `"/* not a comment */"`. Every comment character is replaced with a space and every newline is
    preserved, so the result has the same length and line/column layout as `content` and every
    offset computed against it remains valid.

    This is the comment half of the single lexical pass in `_lex_typescript`; see there for what
    is recognized as a literal (and therefore never searched for comment markers).

    Args:
        content: The full source text to scan.
        allow_jsx: Whether to treat JSX text as markup. Defaults to false because this helper
            does not know the source file extension.

    Returns:
        `content` with every comment's characters (other than newlines) replaced by spaces.
    """
    return _lex_typescript(content, allow_jsx=allow_jsx)[0]


def _scan_typescript(content: str, *, allow_jsx: bool = True) -> tuple[str, str]:
    """Return `(scan, structural_scan)` for `content` from one lexical pass.

    `scan` is `content` with comments blanked. `structural_scan` is `scan` with strings,
    templates, regular expressions, and JSX elements blanked to NUL characters. JSX parsing is
    enabled for TSX input. Both outputs come from the same lexical pass.
    """
    scan, literal_spans = _lex_typescript(content, allow_jsx=allow_jsx)
    masked = list(scan)
    for start, end in literal_spans:
        _blank_span(masked, start, end)
    return scan, "".join(masked)


def _lex_typescript(
    content: str, *, allow_jsx: bool = True
) -> tuple[str, list[tuple[int, int]]]:
    """Run the single lexical pass shared by comment stripping and literal masking.

    Walks `content` once, classifying each position as code, comment, or literal, and returns
    `(scan, literal_spans)`: `content` with comments blanked (every character but a line feed
    replaced by a space) and the half-open `(start, end)` extent of every literal.

    Literals, whose contents are never searched for comment markers or braces:

    - single- and double-quoted strings, with backslash escapes; one that is not closed ends at the
      end of its line;
    - regular-expression literals, found with the `_is_regex_literal_start` heuristic;
    - template literals, from the opening backtick to the matching closing backtick, with backslash
      escapes. The span covers the whole literal, `${...}` expressions included. Inside a `${`,
      the text is code again: comments there are blanked, braces are counted so that the `}`
      matching the `${` is found, and strings, regular expressions, and further template literals
      are recognized in turn, to any nesting depth. Open templates and interpolations are tracked
      on explicit stacks, so nesting depth is not limited by the recursion limit.

    Only outermost literals are reported: anything inside a template literal's span is covered by
    that span, which keeps masking linear in the size of the source however deeply templates nest.

    A template literal that is never closed ends at the end of the file.

    This is a lightweight scan, not a full TypeScript or JSX parser. JSX tag and text regions are
    skipped for structural analysis, while JavaScript inside JSX expression containers is scanned.
    Regular-expression versus division classification remains heuristic in uncommon contexts.

    Args:
        content: The full source text to scan.

    Returns:
        `(scan, literal_spans)`, where `scan` has the same length as `content`.
    """
    chars = list(content)
    literal_spans: list[tuple[int, int]] = []
    length = len(content)
    index = 0
    previous_word = ""
    in_template = False
    template_starts: list[int] = []
    interpolation_braces: list[int] = []
    jsx_modes: list[str] = []
    jsx_depths: list[int] = []
    jsx_return_modes: list[str] = []
    jsx_expression_depths: list[int] = []
    jsx_starts: list[int] = []
    jsx_closing_tags: list[bool] = []
    jsx_outermost: list[bool] = []

    while index < length:
        character = content[index]

        if jsx_modes and jsx_modes[-1] == "text":
            if character == "<":
                jsx_modes[-1] = "tag"
                jsx_closing_tags[-1] = content.startswith("</", index)
                index += 2 if jsx_closing_tags[-1] else 1
            elif character == "{":
                jsx_return_modes.append("text")
                jsx_modes[-1] = "expression"
                jsx_expression_depths[-1] = 0
                previous_word = "{"
                index += 1
            else:
                index += 1
            continue

        if jsx_modes and jsx_modes[-1] == "tag":
            if character in "'\"":
                index = _quoted_string_end(content, index)
            elif character == "{":
                jsx_return_modes.append("tag")
                jsx_modes[-1] = "expression"
                jsx_expression_depths[-1] = 0
                previous_word = "{"
                index += 1
            elif character == ">":
                previous = index - 1
                while previous >= jsx_starts[-1] and content[previous].isspace():
                    previous -= 1
                self_closing = previous >= jsx_starts[-1] and content[previous] == "/"
                if jsx_closing_tags[-1]:
                    jsx_depths[-1] -= 1
                elif not self_closing:
                    jsx_depths[-1] += 1

                index += 1
                if jsx_depths[-1] == 0:
                    start = jsx_starts.pop()
                    outermost = jsx_outermost.pop()
                    jsx_modes.pop()
                    jsx_depths.pop()
                    jsx_return_modes.pop()
                    jsx_expression_depths.pop()
                    jsx_closing_tags.pop()
                    if outermost:
                        literal_spans.append((start, index))
                    previous_word = "literal"
                else:
                    jsx_modes[-1] = "text"
            else:
                index += 1
            continue

        if jsx_modes and jsx_modes[-1] == "expression":
            closes_template_interpolation = (
                character == "}"
                and interpolation_braces
                and interpolation_braces[-1] == 0
            )
            if closes_template_interpolation:
                pass
            elif character == "{":
                jsx_expression_depths[-1] += 1
            elif character == "}":
                if jsx_expression_depths[-1] == 0:
                    jsx_modes[-1] = jsx_return_modes.pop()
                    previous_word = "literal"
                    index += 1
                    continue
                jsx_expression_depths[-1] -= 1

        if in_template:
            if character == "\\":
                index += 2
            elif character == "`":
                start = template_starts.pop()
                if not template_starts:
                    literal_spans.append((start, index + 1))
                in_template = False
                previous_word = "literal"
                index += 1
            elif content.startswith("${", index):
                interpolation_braces.append(0)
                in_template = False
                previous_word = "{"
                index += 2
            else:
                index += 1
        elif character.isspace():
            index += 1
        elif content.startswith("//", index):
            index = _blank_line_comment(chars, content, index)
        elif content.startswith("/*", index):
            index = _blank_block_comment(chars, content, index)
        elif character == "/" and _is_regex_literal_start(chars, index, previous_word):
            start = index
            index = _regex_literal_end(content, index)
            if not template_starts:
                literal_spans.append((start, index))
            previous_word = "literal"
        elif character in "'\"":
            start = index
            index = _quoted_string_end(content, index)
            if not template_starts:
                literal_spans.append((start, index))
            previous_word = "literal"
        elif character == "`":
            template_starts.append(index)
            in_template = True
            index += 1
        elif allow_jsx and character == "<" and _is_jsx_element_start(content, index, previous_word):
            jsx_modes.append("tag")
            jsx_depths.append(0)
            jsx_return_modes.append("text")
            jsx_expression_depths.append(0)
            jsx_starts.append(index)
            jsx_closing_tags.append(False)
            jsx_outermost.append(not jsx_modes[:-1])
            index += 1
        elif character.isalnum() or character in "_$":
            start = index
            while index < length and (content[index].isalnum() or content[index] in "_$"):
                index += 1
            previous_word = content[start:index]
        else:
            if interpolation_braces:
                if character == "{":
                    interpolation_braces[-1] += 1
                elif character == "}":
                    if interpolation_braces[-1] == 0:
                        interpolation_braces.pop()
                        in_template = True
                    else:
                        interpolation_braces[-1] -= 1
            previous_word = character
            index += 1

    if template_starts:
        literal_spans.append((template_starts[0], length))
    if jsx_starts and jsx_outermost and jsx_outermost[0]:
        literal_spans.append((jsx_starts[0], length))
    return "".join(chars), literal_spans


def _blank_line_comment(chars: list[str], content: str, start: int) -> int:
    """Blank a `//` comment up to, but not including, its line feed; return where it ends."""
    index = start
    while index < len(content) and content[index] != "\n":
        chars[index] = " "
        index += 1
    return index


def _blank_block_comment(chars: list[str], content: str, start: int) -> int:
    """Blank a `/* ... */` comment, keeping its line feeds; return where it ends.

    An unterminated comment is blanked to the end of the file.
    """
    chars[start] = chars[start + 1] = " "
    index = start + 2
    while index < len(content):
        if content.startswith("*/", index):
            chars[index] = chars[index + 1] = " "
            return index + 2
        if content[index] != "\n":
            chars[index] = " "
        index += 1
    return index


def _quoted_string_end(content: str, start: int) -> int:
    """Return the index just past the `'` or `"` string starting at `start`.

    A backslash escapes the character after it. A string that reaches a line break before its
    closing quote ends at that line break, which is not consumed.
    """
    quote = content[start]
    index = start + 1
    while index < len(content):
        character = content[index]
        if character in "\r\n":
            return index
        if character == "\\":
            index += 2
        elif character == quote:
            return index + 1
        else:
            index += 1
    return index


def _regex_literal_end(content: str, start: int) -> int:
    """Return the index just past the regular-expression literal starting at `start`.

    Handles escapes, `[...]` classes in which a `/` does not close the literal, trailing flags, and
    an end at the line break.
    """
    index = start + 1
    in_character_class = False
    while index < len(content) and content[index] not in "\r\n":
        if content[index] == "\\":
            index += 2
            continue
        if content[index] == "[":
            in_character_class = True
        elif content[index] == "]":
            in_character_class = False
        elif content[index] == "/" and not in_character_class:
            index += 1
            while index < len(content) and content[index].isalpha():
                index += 1
            break
        index += 1
    return index


def _blank_span(masked: list[str], start: int, end: int) -> None:
    """Blank a source span without changing offsets or line breaks."""
    for position in range(start, min(end, len(masked))):
        if masked[position] not in ("\n", "\r"):
            masked[position] = "\x00"


def _matching_angle_bracket(content: str, opening: int) -> int | None:
    """Return the closing angle bracket for a balanced generic parameter list."""
    depth = 0
    quote: str | None = None
    escaped = False
    for position in range(opening, len(content)):
        character = content[position]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in "\"'`":
            quote = character
        elif character == "<":
            depth += 1
        elif character == ">" and not (
            position > opening and content[position - 1] == "="
        ):
            depth -= 1
            if depth == 0:
                return position
    return None


def _is_jsx_element_start(content: str, index: int, previous_word: str) -> bool:
    """Recognize JSX starts in common expression positions without parsing type syntax."""
    if index + 1 >= len(content) or not (
        content[index + 1] == ">" or content[index + 1].isalpha() or content[index + 1] in "_$"
    ):
        return False

    previous = index - 1
    while previous >= 0 and content[previous].isspace():
        previous -= 1

    # A generic arrow function in TSX is not a JSX element. Match the
    # complete type-parameter list because constraints can contain nested
    # generic types, such as `T extends Record<string, unknown>`.
    closing = _matching_angle_bracket(content, index)
    if closing is not None:
        following = closing + 1
        while following < len(content) and content[following].isspace():
            following += 1
        header = content[index + 1 : closing]
        if following < len(content) and content[following] == "(" and (
            "," in header or "extends" in header or "=" in header
        ):
            return False

    if previous_word in {"return", "default"}:
        return True
    if previous < 0 or content[previous] in "=(:,[!&|?{};":
        return True
    return content[previous] == ">" and previous > 0 and content[previous - 1] == "="


def _is_regex_literal_start(scan: Sequence[str], index: int, previous_word: str) -> bool:
    """Recognize common expression positions where slash starts a regex literal."""
    if previous_word in {
        "return",
        "throw",
        "case",
        "delete",
        "void",
        "typeof",
        "instanceof",
        "in",
        "of",
        "yield",
        "await",
    }:
        return True
    previous = index - 1
    while previous >= 0 and scan[previous].isspace():
        previous -= 1
    if previous < 0:
        return True
    if scan[previous] in "+-*%":
        return True
    if scan[previous] == ">" and previous > 0 and scan[previous - 1] == "=":
        return True
    return scan[previous] in "=(:,[!&|?{};"



def _compute_opaque_depths(scan: str, namespace_opens: set[int]) -> list[int]:
    """Compute opaque brace depth at every source position.

    Namespace/module braces are transparent, so declarations within them remain file-scope
    declarations for this parser. Other braces, including function bodies, class bodies, arrow
    bodies, callbacks, control-flow blocks and object literals, are opaque. `scan` must have
    quoted literals masked first; offsets remain identical to the original comment-stripped
    source.
    """
    depths = [0] * (len(scan) + 1)
    stack: list[bool] = []
    opaque_depth = 0
    for index, character in enumerate(scan):
        if character == "\x00":
            depths[index] = -1
            continue
        depths[index] = opaque_depth
        if character == "{":
            is_opaque = index not in namespace_opens
            stack.append(is_opaque)
            if is_opaque:
                opaque_depth += 1
        elif character == "}" and stack and stack.pop():
            opaque_depth -= 1
    depths[len(scan)] = opaque_depth
    return depths


def _extract_namespaces(
    content: str, scan: str, lines: list[str], opaque_depths: list[int]
) -> tuple[ParsedModule, ...]:
    """Collect namespace/module blocks outside opaque executable/type scopes.

    Namespace declarations can be nested in another namespace, but a match inside a function,
    class or other opaque block is not emitted as a file-scope module.
    """
    del lines
    modules = [
        ParsedModule(
            name=match["name"].strip("\"\'"),
            line_number=line_number_at(content, match.start()),
        )
        for match in _NAMESPACE_PATTERN.finditer(scan)
        if opaque_depths[match.start()] == 0
    ]
    modules.extend(
        ParsedModule(name="global", line_number=line_number_at(content, match.start()))
        for match in _GLOBAL_AUGMENTATION_PATTERN.finditer(scan)
        if opaque_depths[match.start()] == 0
    )
    return tuple(sorted(modules, key=lambda module: module.line_number))


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


def _extract_interfaces(
    content: str, scan: str, structural_scan: str, opaque_depths: list[int]
) -> tuple[ParsedInterface, ...]:
    """Collect interface declarations with their method signatures and data properties.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        structural_scan: `scan` with string literals masked, used for every brace, delimiter, and
            member-boundary decision, and to find method declarations, so that a quote character,
            a brace, or a `name(` inside a string, template, or regex literal cannot change the
            interface body's extent, a member's boundaries, or which text reads as a method.
            Method names, parameters, and return types are still read from `scan` and `content`;
            the scans have equal length, so offsets are interchangeable.
        opaque_depths: Opaque brace depth at every source position.

    Returns:
        Every file-scope interface, in source order.
    """
    interfaces: list[ParsedInterface] = []
    for match in _INTERFACE_PATTERN.finditer(scan):
        if opaque_depths[match.start()] != 0:
            continue
        header = _read_declaration_header(structural_scan, scan, match.end())
        if header is None:
            continue
        open_index = header[0]
        close_index = find_matching_brace(structural_scan, open_index)
        properties, property_spans = _extract_properties(
            content, scan, structural_scan, open_index + 1, close_index
        )
        method_matches = _method_matches(
            structural_scan, open_index + 1, close_index, commas_separate=True
        )
        methods = tuple(
            _build_method(content, scan, structural_scan, method_match)
            for method_match in method_matches
            if not _inside_any(method_match.start(), property_spans)
        )
        interfaces.append(
            ParsedInterface(
                name=match["name"],
                methods=methods,
                line_number=line_number_at(content, match.start()),
                properties=properties,
            )
        )
    return tuple(interfaces)


#: Trailing tokens that mean a member's type continues on the next line.
_CONTINUATION_SUFFIXES = (":", "|", "&", "=>", "?")

#: Trailing words that mean a member's type continues on the next line.
_CONTINUATION_WORDS = frozenset({"extends", "keyof", "typeof", "infer", "unique"})

#: Leading tokens that mean a line continues the previous member's type.
_CONTINUATION_PREFIXES = ("|", "&", "=>", "?", ":")

_TRAILING_WORD_PATTERN = re.compile(r"[\w$]+$")
_LEADING_EXTENDS_PATTERN = re.compile(r"extends\b")
_PROPERTY_IDENTIFIER_PATTERN = re.compile(r"[\w$]+")
_PROPERTY_NUMBER_PATTERN = re.compile(r"(?:\d|\.\d)[\w.]*")


def _extract_properties(
    content: str, scan: str, structural_scan: str, body_start: int, body_end: int
) -> tuple[tuple[ParsedProperty, ...], tuple[tuple[int, int], ...]]:
    """Collect the data properties declared directly in one interface body.

    The body is first cut into members at top-level separators (see `_split_members`); each
    member is then classified, so nested generics, function types, and object types are never
    inspected by a pattern that could be confused by their delimiters.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        structural_scan: `scan` with string literals masked.
        body_start: Index immediately after the interface's opening brace.
        body_end: Index of the interface's closing brace.

    Returns:
        A pair of: every property found, in source order, and each property member's
        `(start, end)` span (used to keep text inside a property's type from being mistaken for
        a method signature).
    """
    properties: list[ParsedProperty] = []
    spans: list[tuple[int, int]] = []
    for start, end in _split_members(structural_scan, body_start, body_end):
        parsed = _parse_property(content, scan, structural_scan, start, end)
        if parsed is not None:
            properties.append(parsed)
            spans.append((start, end))
    return tuple(properties), tuple(spans)


def _split_members(structural_scan: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cut an interface body into `(start, end)` member spans.

    A member ends at a `;` or `,` that is not nested inside `{}`, `()`, `[]`, or `<>`, or at a
    line break outside every such nesting when the member is complete (see
    `_ends_member_at_newline`), so newline-separated members work without a separator. The `>`
    of an arrow `=>` does not close an angle bracket.

    Args:
        structural_scan: Comment-blanked source with string literals masked.
        start: Index immediately after the interface's opening brace.
        end: Index of the interface's closing brace.

    Returns:
        One span per member, in source order. A span may be blank; callers skip those.
    """
    spans: list[tuple[int, int]] = []
    member_start = start
    nesting = 0
    angle = 0
    for index in range(start, end):
        character = structural_scan[index]
        if character in "{([":
            nesting += 1
        elif character in "})]":
            nesting = max(0, nesting - 1)
        elif character == "<":
            angle += 1
        elif character == ">":
            if structural_scan[index - 1] != "=":
                angle = max(0, angle - 1)
        elif nesting == 0 and angle == 0 and (
            character in ";,"
            or (
                character == "\n"
                and _ends_member_at_newline(structural_scan, member_start, index, end)
            )
        ):
            spans.append((member_start, index))
            member_start = index + 1
    spans.append((member_start, end))
    return spans


def _ends_member_at_newline(
    structural_scan: str, member_start: int, newline: int, end: int
) -> bool:
    """Report whether a line break at `newline` finishes the member that began at `member_start`.

    A line break finishes a member unless the member is still blank or its type visibly continues
    on the next line: the text so far ends in a dangling operator such as `:`, `|`, `&`, `=>`, or
    `extends`, or the next line begins with `|`, `&`, `=>`, `?`, `:`, or the `extends` keyword of a
    conditional type. A line that begins with a member *named* `extends` does not continue the
    type (see `_extends_names_a_member`).
    """
    head = structural_scan[member_start:newline].rstrip()
    if not head or head.endswith(_CONTINUATION_SUFFIXES):
        return False
    trailing_word = _TRAILING_WORD_PATTERN.search(head)
    if trailing_word is not None and trailing_word.group() in _CONTINUATION_WORDS:
        return False
    next_index = _skip_whitespace(structural_scan, newline + 1, end)
    if structural_scan.startswith(_CONTINUATION_PREFIXES, next_index, end):
        return False
    keyword = _LEADING_EXTENDS_PATTERN.match(structural_scan, next_index, end)
    return keyword is None or _extends_names_a_member(structural_scan, keyword.end(), end)


def _extends_names_a_member(structural_scan: str, word_end: int, end: int) -> bool:
    """Report whether a line-leading word `extends`, ending at `word_end`, names a member.

    At the start of a line, `extends` is either the keyword of a conditional type that continues
    from the previous line (`T` / `extends string ? A : B`) or the name of the next member of an
    interface or class (`extends?: string`, `extends(): void`). A conditional's `extends` is
    followed by whitespace and the type it tests against, while a member's name is followed by
    what follows any member name:

    - `<` right after the word, or `(` right after the word when the parenthesized list is
      followed by `:`, `;`, `,`, `{`, `}`, a line break, or the end -- a method (`extends(): void`,
      `extends<T>(x: T): T`). So `extends(infer U)[] ? A : B` is still a conditional;
    - after optional spaces or tabs, one of `?`, `:`, `;`, `,`, `}`, or the end of the text -- a
      property or an optional member (`extends: string`, `extends?: string`).

    Anything else, including a line break right after the word, is read as the keyword of a
    conditional type, which is the behavior for every other line that begins with `extends`.

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        word_end: Index just after the word `extends`.
        end: Index where the text being scanned ends.

    Returns:
        True if the word is a member's name rather than a conditional type's keyword.
    """
    if word_end >= end:
        return True
    character = structural_scan[word_end]
    if character == "<":
        return True
    if character == "(":
        after = _group_end(structural_scan, word_end)
        while after < end and structural_scan[after] in " \t":
            after += 1
        return after >= end or structural_scan[after] in ":;,{}\r\n"
    index = word_end
    while index < end and structural_scan[index] in " \t":
        index += 1
    return index >= end or structural_scan[index] in "?:;,}"


def _parse_property(
    content: str, scan: str, structural_scan: str, start: int, end: int
) -> ParsedProperty | None:
    """Classify one interface member and build a `ParsedProperty` if it is a data property.

    Method signatures (including optional and generic ones), getters, setters, call signatures,
    construct signatures, index signatures, and computed names are not properties and yield
    None, as does anything that is not a well-formed property declaration.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        structural_scan: `scan` with string literals masked.
        start: Index where the member's span begins.
        end: Index where the member's span ends.

    Returns:
        The property, or None if the member is not a data property.
    """
    member_start = _skip_whitespace(structural_scan, start, end)
    first = _read_property_name(scan, structural_scan, member_start, end)
    if first is None:
        return None
    name, name_end, is_identifier = first
    cursor = _skip_whitespace(structural_scan, name_end, end)

    # `readonly` is a modifier only when a name follows it; otherwise it is the property's name.
    is_readonly = False
    if is_identifier and name == "readonly" and _follows_as_name(structural_scan, cursor, end):
        second = _read_property_name(scan, structural_scan, cursor, end)
        if second is None:
            return None
        is_readonly = True
        name, name_end, is_identifier = second
        cursor = _skip_whitespace(structural_scan, name_end, end)

    # `get x()` / `set x(v)` are accessors; `get: T` and `get?: T` are ordinary properties.
    if is_identifier and name in ("get", "set") and _follows_as_name(structural_scan, cursor, end):
        return None

    is_optional = cursor < end and structural_scan[cursor] == "?"
    if is_optional:
        cursor = _skip_whitespace(structural_scan, cursor + 1, end)

    type_annotation: str | None = None
    if cursor < end:
        if structural_scan[cursor] != ":":
            return None
        type_annotation = " ".join(scan[cursor + 1 : end].split()) or None

    return ParsedProperty(
        name=name,
        type_annotation=type_annotation,
        is_optional=is_optional,
        is_readonly=is_readonly,
        line_number=line_number_at(content, member_start),
    )


def _skip_whitespace(structural_scan: str, index: int, end: int) -> int:
    """Return the index of the first non-whitespace character in `[index, end)`, or `end`."""
    while index < end and structural_scan[index].isspace():
        index += 1
    return index


def _follows_as_name(structural_scan: str, index: int, end: int) -> bool:
    """Report whether the member text at `index` is a further name rather than `:`/`?`/`(`/`<`.

    Distinguishes the modifier or accessor keyword in `readonly x: T` / `get x(): T` from a
    property that is itself called `readonly` / `get` (`readonly: T`, `get?: T`, `get(): T`).
    """
    return index < end and structural_scan[index] not in ":?(<"


def _read_property_name(
    scan: str, structural_scan: str, index: int, end: int
) -> tuple[str, int, bool] | None:
    """Read one property name -- identifier, quoted string, or numeric literal -- at `index`.

    Args:
        scan: Comment-blanked source, which still holds the text of string literals.
        structural_scan: `scan` with string literals masked.
        index: Where the name is expected to start.
        end: End of the member's span.

    Returns:
        `(name, end_index, is_identifier)`, with a quoted name returned without its quotes, or
        None if no name starts at `index` (for example `(`, `[`, or `<`, which begin call,
        index, and generic signatures).
    """
    if index >= end:
        return None
    if structural_scan[index] == "\x00":
        stop = index
        while stop < end and structural_scan[stop] == "\x00":
            stop += 1
        literal = scan[index:stop]
        if len(literal) >= 2 and literal[0] in "'\"" and literal[-1] == literal[0]:
            return literal[1:-1], stop, False
        return None
    number = _PROPERTY_NUMBER_PATTERN.match(structural_scan, index, end)
    if number is not None:
        return number.group(), number.end(), False
    identifier = _PROPERTY_IDENTIFIER_PATTERN.match(structural_scan, index, end)
    if identifier is not None:
        return identifier.group(), identifier.end(), True
    return None


def _extract_classes(
    content: str, scan: str, structural_scan: str, lines: list[str], opaque_depths: list[int]
) -> tuple[tuple[ParsedClass, ...], tuple[tuple[int, int], ...]]:
    """Collect every `class` declaration and its methods.

    Declarations and member text are read from `scan` and `content`. Where a position or an
    extent is decided -- where the class body opens (`_read_declaration_header`), the matching
    closing brace of that body, and which `name(` texts are method declarations
    (`_method_matches`) -- `structural_scan` is used instead, so a brace or a `name(` inside a
    string, template literal, or regex literal cannot move a boundary or be read as a method.
    Both scans have the same length as `content`, so offsets are interchangeable.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        structural_scan: `scan` with string, template, and regex literals masked.
        lines: `content` split into lines.
        opaque_depths: Opaque brace depth at every source position.

    Returns:
        A pair of: every class found, and every class body's `(start, end)` span (used by
        `_extract_functions` to exclude methods from the free-function scan).
    """
    classes: list[ParsedClass] = []
    spans: list[tuple[int, int]] = []

    for match in _CLASS_PATTERN.finditer(scan):
        if opaque_depths[match.start()] != 0:
            continue
        header = _read_declaration_header(structural_scan, scan, match.end())
        if header is None:
            continue
        open_index, extends, implements = header
        close_index = find_matching_brace(structural_scan, open_index)
        spans.append((open_index + 1, close_index))

        base_classes: list[str] = []
        if extends:
            base_classes.append(extends)
        if implements:
            base_classes.extend(split_top_level(implements))

        methods = tuple(
            _build_method(content, scan, structural_scan, method_match)
            for method_match in _method_matches(
                structural_scan, open_index + 1, close_index, commas_separate=False
            )
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


_HERITAGE_KEYWORD_PATTERN = re.compile(r"(?:extends|implements)\b")
_HERITAGE_NAME_PATTERN = re.compile(r"[\w$.]+")


def _read_declaration_header(
    structural_scan: str, scan: str, name_end: int
) -> tuple[int, str | None, str | None] | None:
    """Find the body of a `class` or `interface` declaration whose name ends at `name_end`.

    Reads the header as syntax on `structural_scan` instead of matching it with one regular
    expression, so type parameters spread over several lines, an object-type constraint
    (`<T extends { id: string }>`), and an object type inside an `extends` clause
    (`extends Base<{ a: 1 }>`) are skipped as part of the header rather than taken for the body:

    - optional type parameters `<...>`, skipped as a balanced group (`_skip_angle_group`);
    - then any number of `extends` / `implements` clauses, each a comma-separated list of
      dotted names that may carry type arguments;
    - then the `{` that opens the body.

    Anything else -- including the end of the text -- means this is not a declaration with a body,
    so the search stops there instead of running on into later code.

    Args:
        structural_scan: `scan` with string, template, and regex literals masked.
        scan: `content` with comments blanked out; the `implements` text is read from here.
        name_end: Index just after the declaration's name.

    Returns:
        `(open_index, extends, implements)`: the index of the body's `{`, the first dotted name
        after `extends` (or None), and the text of the `implements` list (or None); or None if
        no body follows the header.
    """
    length = len(structural_scan)
    index = _skip_whitespace(structural_scan, name_end, length)
    if index < length and structural_scan[index] == "<":
        index = _skip_angle_group(structural_scan, index)
        if index < 0:
            return None
    extends: str | None = None
    implements_start: int | None = None
    while True:
        index = _skip_whitespace(structural_scan, index, length)
        if index >= length:
            return None
        if structural_scan[index] == "{":
            implements = scan[implements_start:index].strip() if implements_start is not None else ""
            return index, extends, implements or None
        keyword = _HERITAGE_KEYWORD_PATTERN.match(structural_scan, index)
        if keyword is None:
            return None
        index = keyword.end()
        is_extends = keyword.group() == "extends"
        if not is_extends:
            implements_start = index
        first_item = True
        while True:
            index = _skip_whitespace(structural_scan, index, length)
            name = _HERITAGE_NAME_PATTERN.match(structural_scan, index)
            if name is None:
                return None
            if is_extends and first_item and extends is None:
                extends = name.group()
            first_item = False
            index = _skip_whitespace(structural_scan, name.end(), length)
            if index < length and structural_scan[index] == "<":
                index = _skip_angle_group(structural_scan, index)
                if index < 0:
                    return None
                index = _skip_whitespace(structural_scan, index, length)
            if index < length and structural_scan[index] == ",":
                index += 1
                continue
            break


def _skip_angle_group(structural_scan: str, open_index: int) -> int:
    """Return the index just past the `<...>` group opened at `open_index`, or -1 if unclosed.

    Nested `<>` are counted wherever they occur, so the angle brackets inside an object-type
    constraint or a nested generic do not end the group early, and braces and parentheses inside
    it are simply skipped. The `>` of an arrow `=>` is not a closer.
    """
    angle = 0
    for index in range(open_index, len(structural_scan)):
        character = structural_scan[index]
        if character == "<":
            angle += 1
        elif character == ">" and structural_scan[index - 1] != "=":
            angle -= 1
            if angle == 0:
                return index + 1
    return -1


#: Words that can precede a member's name inside the same member.
_MEMBER_MODIFIERS = frozenset(
    {
        "public",
        "private",
        "protected",
        "static",
        "readonly",
        "abstract",
        "async",
        "override",
        "declare",
        "accessor",
        "get",
        "set",
    }
)

#: Words that continue an expression, so a name right after one does not begin a member.
_EXPRESSION_WORDS = frozenset(
    {
        "new",
        "typeof",
        "delete",
        "await",
        "yield",
        "return",
        "throw",
        "instanceof",
        "in",
        "of",
        "as",
        "extends",
        "implements",
        "keyof",
        "is",
        "else",
        "case",
    }
)

#: Characters after which an expression continues, so a name right after one (even on the next
#: line) does not begin a member.
_CONTINUATION_CHARACTERS = frozenset("=:|&?<+-*/%^~!.@,([")


def _method_matches(
    structural_scan: str, body_start: int, body_end: int, *, commas_separate: bool
) -> list[re.Match[str]]:
    """Find the method declarations directly inside a class or interface body.

    `_METHOD_PATTERN` matches any `name(` in the body, which includes decorator calls
    (`@Input()`), calls in field initializers (`cache = new Map<string, number>()`), and text in
    a method's own signature (`typeof import("x")`, `new () => T`, `a = f(1)`). A match is a
    method declaration only if it passes all of these:

    - it is not nested inside any `()`, `[]`, or `{}` opened in the body;
    - it begins a member (`_starts_member`): after the body's `{`, a `;`, a closing `}`, (in an
      interface) a `,`, after a line break that ends a complete member, or after the modifiers
      and decorators that belong to the same member;
    - it does not start inside an already accepted method's signature (parameters and return
      type).

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        body_start: Index just after the body's opening `{`.
        body_end: Index of the body's closing `}`.
        commas_separate: Whether a top-level `,` separates members (true for interfaces).

    Returns:
        The accepted matches, in source order.
    """
    depths = _nesting_depths(structural_scan, body_start, body_end)
    accepted: list[re.Match[str]] = []
    skip_until = body_start
    for match in _METHOD_PATTERN.finditer(structural_scan, body_start, body_end):
        start = match.start()
        if start < skip_until or depths[start - body_start] != 0:
            continue
        if not _starts_member(structural_scan, body_start, start, commas_separate):
            continue
        accepted.append(match)
        skip_until = _signature_end(structural_scan, match)
    return accepted


def _nesting_depths(structural_scan: str, start: int, end: int) -> list[int]:
    """Return, for each index in `[start, end)`, how many `()`, `[]`, `{}` are open before it."""
    depths: list[int] = []
    depth = 0
    for index in range(start, end):
        depths.append(depth)
        character = structural_scan[index]
        if character in "([{":
            depth += 1
        elif character in ")]}" and depth > 0:
            depth -= 1
    return depths


def _signature_end(structural_scan: str, match: re.Match[str]) -> int:
    """Return the index where the signature of the method matched by `match` ends.

    That is the end of its return type annotation, or just past the parameter list if there is
    none; the method body, if any, is not part of the signature.
    """
    params_close = find_matching_paren(structural_scan, match.end() - 1)
    span = _return_type_span(structural_scan, params_close)
    return span[1] if span is not None else params_close + 1


def _starts_member(
    structural_scan: str, body_start: int, position: int, commas_separate: bool
) -> bool:
    """Report whether a member of a class or interface body begins at `position`.

    Looks back from `position` over the modifiers (`public`, `static`, `async`, `override`, ...)
    and decorators (`@Name`, `@Name(...)`) that belong to the same member, then asks whether what
    precedes them ends the previous member: the start of the body, a `;`, a closing `}`, (when
    `commas_separate`) a `,`, or anything at all if a line break intervenes and the previous
    text is a complete member -- that is, it does not end in an operator or a word such as `new`
    or `typeof` that leaves an expression unfinished.

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        body_start: Index just after the body's opening `{`.
        position: Index where a method match begins.
        commas_separate: Whether a top-level `,` separates members (true for interfaces).

    Returns:
        True if a member begins at `position`.
    """
    cursor = position
    while True:
        previous = cursor - 1
        while previous >= body_start and structural_scan[previous].isspace():
            previous -= 1
        if previous < body_start:
            return True
        character = structural_scan[previous]
        line_break = "\n" in structural_scan[previous + 1 : cursor]
        if character in ";}" or (character == "," and commas_separate):
            return True
        if character.isalnum() or character in "_$":
            word_start = previous
            while word_start > body_start and (
                structural_scan[word_start - 1].isalnum() or structural_scan[word_start - 1] in "_$"
            ):
                word_start -= 1
            word = structural_scan[word_start : previous + 1]
            if word in _MEMBER_MODIFIERS:
                cursor = word_start
                continue
            decorator = _decorator_start(structural_scan, body_start, previous)
            if decorator is not None:
                cursor = decorator
                continue
            return line_break and word not in _EXPRESSION_WORDS
        if character == ")":
            decorator = _decorator_start(structural_scan, body_start, previous)
            if decorator is not None:
                cursor = decorator
                continue
            return line_break
        if character == ">" and previous > body_start and structural_scan[previous - 1] == "=":
            return False
        if character in _CONTINUATION_CHARACTERS:
            return False
        return line_break


def _decorator_start(structural_scan: str, body_start: int, last: int) -> int | None:
    """Return the index of the `@` of the decorator that ends at `last`, or None.

    `last` is either the closing `)` of a decorator call (`@Name(...)`, `@ns.Name(...)`,
    `@Name<T>(...)`, `@Name (...)`) or the last character of a decorator written without arguments
    (`@Name`).
    """
    index = last
    if structural_scan[index] == ")":
        nesting = 0
        while index >= body_start:
            character = structural_scan[index]
            if character == ")":
                nesting += 1
            elif character == "(":
                nesting -= 1
                if nesting == 0:
                    break
            index -= 1
        else:
            return None
        index -= 1
        while index >= body_start and structural_scan[index].isspace():
            index -= 1
        if index > body_start and structural_scan[index] == ">":
            if structural_scan[index - 1] == "=":
                return None
            angle = 0
            while index >= body_start:
                character = structural_scan[index]
                if character == ">" and structural_scan[index - 1] != "=":
                    angle += 1
                elif character == "<":
                    angle -= 1
                    if angle == 0:
                        break
                index -= 1
            else:
                return None
            index -= 1
            while index >= body_start and structural_scan[index].isspace():
                index -= 1
    name_end = index
    while index >= body_start and (
        structural_scan[index].isalnum() or structural_scan[index] in "_$."
    ):
        index -= 1
    if index == name_end:
        return None
    if index >= body_start and structural_scan[index] == "@":
        return index
    return None


def _build_method(
    content: str, scan: str, structural_scan: str, match: re.Match[str]
) -> ParsedFunction:
    """Build a `ParsedFunction` for one method found inside a class or interface body.

    The extent of the parameter list, the commas that separate parameters, and the end of the
    return type are all decided on `structural_scan`, so a `)`, `,`, `{`, `}`, or `;` inside a
    string, template, or regex literal -- or a comma inside generic type arguments -- cannot end
    any of them early. The text of every parameter and of the return type is still sliced from the
    original `content`, and the `async` flag is read from `scan`; the three have equal length, so
    offsets are interchangeable.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        structural_scan: `scan` with string, template, and regex literals masked.
        match: A `_METHOD_PATTERN` match, found in either `scan` or `structural_scan`. Only its
            offsets and its name, which are identical in both, are used.

    Returns:
        The corresponding `ParsedFunction`, with `is_method=True`.
    """
    params_open = match.end() - 1
    parameters, return_type = _read_signature(content, structural_scan, params_open)
    return ParsedFunction(
        name=match["name"],
        parameters=parameters,
        return_type=return_type,
        is_async="async" in scan[match.start() : match.start("name")],
        is_method=True,
        line_number=line_number_at(content, match.start()),
    )


#: Characters after which a `<` can only begin type arguments (for example a generic function
#: type such as `cb: <T, U>(a: T) => U`), never a comparison.
_TYPE_ARGUMENT_LEAD_INS = ":|&<(,="


def _read_signature(
    content: str, structural_scan: str, params_open: int
) -> tuple[tuple[str, ...], str | None]:
    """Read the parameters and return type of the callable whose `(` is at `params_open`.

    The one place a signature is read, shared by class methods, interface methods, free
    functions, and arrow functions: the matching `)` is found, the commas between parameters are
    chosen (`_split_parameters`), and the end of the return type is located
    (`_return_type_after`), all on `structural_scan`; every piece of text is sliced from `content`.

    Args:
        content: The original, unmodified file content.
        structural_scan: `content` with comments blanked and literals masked.
        params_open: Index of the parameter list's opening `(`.

    Returns:
        `(parameters, return_type)`: each parameter's original text, and the return type as
        written (None if there is no `: ReturnType` annotation).
    """
    params_close = find_matching_paren(structural_scan, params_open)
    parameters = _split_parameters(content, structural_scan, params_open + 1, params_close)
    return_type = _return_type_after(structural_scan, content, params_close)
    return parameters, return_type


def _split_parameters(
    content: str, structural_scan: str, start: int, end: int
) -> tuple[str, ...]:
    """Split the parameter list at `[start, end)` into one string per parameter.

    A comma separates parameters only when it is outside every `()`, `[]`, `{}`, and outside every
    `<...>` of type arguments, and not inside a string, template, or regex literal (masked in
    `structural_scan`). So `value: Map<string, number>` and `a: "x,y"` are each one parameter.

    A `<` opens type arguments when it directly follows an identifier character (`Map<`,
    `Record<\\n`) and a matching `>` follows with only type syntax between (no `=` assignment and no
    `;` outside nested brackets), or when it follows one of `:|&<(,=` after optional whitespace (a
    generic function type). So `a < b` and `x<y, b = z>c` are comparisons, and their commas still
    separate parameters. A `>` closes type arguments only when some are open and it is not the
    `>` of an arrow `=>`. The text of each parameter is sliced from the original `content` and
    stripped; empty segments are dropped, exactly as `split_top_level` does.

    Args:
        content: The original, unmodified file content.
        structural_scan: `content` with comments blanked and literals masked.
        start: Index just after the parameter list's opening `(`.
        end: Index of the parameter list's closing `)`.

    Returns:
        Each parameter's original text, in order.
    """
    segments: list[str] = []
    segment_start = start
    nesting = 0
    angle = 0
    for index in range(start, end):
        character = structural_scan[index]
        if character in "([{":
            nesting += 1
        elif character in ")]}":
            nesting -= 1
        elif character == "<":
            if _opens_type_arguments(structural_scan, start, end, index):
                angle += 1
        elif character == ">":
            if angle > 0 and structural_scan[index - 1] != "=":
                angle -= 1
        elif character == "," and nesting == 0 and angle == 0:
            segments.append(content[segment_start:index])
            segment_start = index + 1
    segments.append(content[segment_start:end])
    return tuple(segment.strip() for segment in segments if segment.strip())


def _opens_type_arguments(structural_scan: str, start: int, end: int, index: int) -> bool:
    """Report whether the `<` at `index` opens type arguments rather than comparing values.

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        start: Index where the enclosing parameter list's text begins.
        end: Index where it ends.
        index: Index of the `<`.

    Returns:
        True if the `<` directly follows an identifier character and has a matching `>` with only
        type syntax between (`_has_closing_type_argument`), or follows (after optional
        whitespace) one of the characters in `_TYPE_ARGUMENT_LEAD_INS`.
    """
    if index > start:
        before = structural_scan[index - 1]
        if before.isalnum() or before in "_$":
            return _has_closing_type_argument(structural_scan, index, end)
    previous = index - 1
    while previous >= start and structural_scan[previous].isspace():
        previous -= 1
    return previous >= start and structural_scan[previous] in _TYPE_ARGUMENT_LEAD_INS


def _has_closing_type_argument(structural_scan: str, open_index: int, end: int) -> bool:
    """Report whether the `<` at `open_index` is closed by a `>` as type arguments would be.

    Scans forward, counting nested `<>` and skipping the `>` of an arrow `=>`. Type arguments
    contain no assignment, so a top-level `=` or `;` (one outside every `()`, `[]`, `{}`) before
    the matching `>` -- as in the comparison `x<y, b = z>c` -- means the `<` is an operator. A `;`
    inside braces is not top-level: `Record<string, { id: string; name: string }>` is a valid
    type-argument list.

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        open_index: Index of the `<`.
        end: Index where the scan must stop (the end of the parameter list).

    Returns:
        True if a matching `>` is found before any top-level `=` or `;` and before `end`.
    """
    angle = 0
    nesting = 0
    for position in range(open_index, end):
        character = structural_scan[position]
        if character in "([{":
            nesting += 1
        elif character in ")]}":
            nesting -= 1
        elif character == "<":
            angle += 1
        elif character == ">":
            if structural_scan[position - 1] != "=":
                angle -= 1
                if angle == 0:
                    return True
        elif nesting == 0 and (
            character == ";"
            or (character == "=" and not structural_scan.startswith("=>", position))
        ):
            return False
    return False


#: Words after which a type is still expected, so a `{` or `(` that follows begins a type.
_TYPE_START_WORDS = frozenset(
    {"new", "abstract", "readonly", "keyof", "extends", "is", "asserts", "infer", "unique"}
)

#: Words, numbers, and masked literals (NUL characters), as one token.
_TYPE_WORD_PATTERN = re.compile(r"[\w$\x00]+")

_EXTENDS_WORD_PATTERN = re.compile(r"extends\b")


def _return_type_after(scan: str, content: str, params_close: int) -> str | None:
    """Extract a `: ReturnType` annotation immediately following a parameter list.

    The annotation's extent comes from `_return_type_span`, so an object type (`{ a: string }`) or
    a function type (`() => void`) is part of the type, while the `{` that opens a body and the
    `=>` of an arrow function are not.

    Args:
        scan: Text of the same length as `content`, in which the annotation's boundary is found.
            Pass the literal-masked scan so that characters inside a string literal type cannot
            end it early.
        content: The original, unmodified file content; the type text is sliced from here.
        params_close: Index of the parameter list's closing `)`.

    Returns:
        The return type as written, or None if no `: ReturnType` annotation is present.
    """
    span = _return_type_span(scan, params_close)
    if span is None:
        return None
    return content[span[0] : span[1]].strip() or None


def _return_type_span(structural_scan: str, params_close: int) -> tuple[int, int] | None:
    """Locate the `: ReturnType` annotation after a parameter list.

    Reads the annotation as type syntax rather than hunting for a terminating character. At the
    top level of the type (outside every `()`, `[]`, `{}`, and `<>`) it ends at:

    - a `{` that does not begin a type: an object type is recognized by the `{` coming where a
      type is expected -- right after the `:`, a `|`, a `&`, an arrow `=>`, or a word such as
      `extends` -- while a `{` after a complete type opens a method or function body;
    - an arrow `=>` that is not part of a function type. A parenthesized group that is a function
      type's parameter list (`()`, `(x: T)`, `(...rest)`, `(x, y)`, and `(x) =>`; see
      `_starts_function_type`) takes the `=>` that follows it, and the type then continues with
      that function type's return type; any other `=>` belongs to an arrow function;
    - a `;`, a `,`, an `=` that is not part of `=>`, or a closer with no opener (the end of the
      enclosing interface or call);
    - a line break after a complete type, unless the next line continues it with `|`, `&`, `?`,
      `:`, `extends` (or `=>` right after a function type's parameters).

    Everything is decided on `structural_scan`, where literals are masked, so a brace, `;`, or `=`
    inside a string, template, or regex literal never ends the type.

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        params_close: Index of the parameter list's closing `)`.

    Returns:
        `(start, end)`: the index just after the `:` and the index where the annotation ends
        (the terminating character's position, or the end of the text); or None if the parameter
        list is not followed by a `:`.
    """
    length = len(structural_scan)
    colon = _skip_whitespace(structural_scan, params_close + 1, length)
    if colon >= length or structural_scan[colon] != ":":
        return None
    start = colon + 1
    nesting = 0
    angle = 0
    at_type_start = True
    awaiting_arrow = False
    seen_token = False
    group_at_type_start = False
    group_is_function_head = False
    index = start
    while index < length:
        character = structural_scan[index]
        in_group = nesting > 0 or angle > 0
        is_arrow = character == "=" and structural_scan.startswith("=>", index)
        if not in_group and not character.isspace() and not is_arrow:
            awaiting_arrow = False
        if character == "\n":
            if (
                not in_group
                and seen_token
                and not at_type_start
                and not _continues_type(structural_scan, index + 1, awaiting_arrow)
            ):
                return start, index
            index += 1
        elif character.isspace():
            index += 1
        elif is_arrow:
            if not in_group:
                if not awaiting_arrow:
                    return start, index
                awaiting_arrow = False
                at_type_start = True
            index += 2
        elif character in "([{":
            if not in_group:
                if character == "{" and not at_type_start:
                    return start, index
                group_at_type_start = at_type_start
                group_is_function_head = (
                    character == "(" and at_type_start and _starts_function_type(structural_scan, index)
                )
                seen_token = True
            nesting += 1
            index += 1
        elif character in ")]}":
            if not in_group:
                return start, index
            nesting -= 1
            if nesting <= 0 and angle == 0:
                nesting = 0
                at_type_start = False
                awaiting_arrow = group_is_function_head and character == ")"
            index += 1
        elif character == "<":
            if not in_group:
                group_at_type_start = at_type_start
                group_is_function_head = False
                seen_token = True
            angle += 1
            index += 1
        elif character == ">":
            if angle > 0:
                angle -= 1
                if angle == 0 and nesting == 0:
                    at_type_start = group_at_type_start
            index += 1
        elif in_group:
            index += 1
        elif character in ";,=":
            return start, index
        elif character in "|&?:":
            at_type_start = True
            seen_token = True
            index += 1
        else:
            word = _TYPE_WORD_PATTERN.match(structural_scan, index)
            if word is None:
                at_type_start = False
                index += 1
            else:
                at_type_start = word.group() in _TYPE_START_WORDS
                index = word.end()
            seen_token = True
    return start, length


def _continues_type(structural_scan: str, index: int, awaiting_arrow: bool) -> bool:
    """Report whether the text from `index` (the line after a line break) continues a type.

    A type continues on the next line when that line begins with `|`, `&`, `?`, `:`, or the
    `extends` keyword of a conditional type, or with `=>` when the type so far ends in a function
    type's parameter list. A line that begins with a member *named* `extends` -- `extends(): void`,
    `extends?: string` -- starts the next member instead (see `_extends_names_a_member`).
    """
    length = len(structural_scan)
    next_index = _skip_whitespace(structural_scan, index, length)
    if structural_scan.startswith(("|", "&", "?", ":"), next_index):
        return True
    if awaiting_arrow and structural_scan.startswith("=>", next_index):
        return True
    keyword = _EXTENDS_WORD_PATTERN.match(structural_scan, next_index)
    return keyword is not None and not _extends_names_a_member(structural_scan, keyword.end(), length)


def _starts_function_type(structural_scan: str, open_paren: int) -> bool:
    """Report whether the `(` at `open_paren`, where a type is expected, opens a function type.

    Mirrors how TypeScript tells `(a: T) => R` from a parenthesized type such as `(A | B)[]`:
    the parentheses hold parameters when they are empty, begin with `...`, or begin with a name
    (or a destructuring pattern) followed by `:`, `,`, `?`, or `=`, or by `)` and then `=>`. A
    string literal is never a parameter name.

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        open_paren: Index of the `(`.

    Returns:
        True if the parenthesized group is a function type's parameter list.
    """
    length = len(structural_scan)
    index = _skip_whitespace(structural_scan, open_paren + 1, length)
    if index >= length:
        return False
    if structural_scan[index] == ")" or structural_scan.startswith("...", index):
        return True
    if structural_scan[index] in "{[":
        index = _group_end(structural_scan, index)
    else:
        word = _TYPE_WORD_PATTERN.match(structural_scan, index)
        if word is None or structural_scan[index] == "\x00":
            return False
        index = word.end()
    index = _skip_whitespace(structural_scan, index, length)
    if index >= length:
        return False
    if structural_scan[index] in ":,?=":
        return True
    if structural_scan[index] == ")":
        after = _skip_whitespace(structural_scan, index + 1, length)
        return structural_scan.startswith("=>", after)
    return False


def _group_end(structural_scan: str, open_index: int) -> int:
    """Return the index just past the `(`, `[`, or `{` group opened at `open_index`."""
    nesting = 0
    for index in range(open_index, len(structural_scan)):
        character = structural_scan[index]
        if character in "([{":
            nesting += 1
        elif character in ")]}":
            nesting -= 1
            if nesting == 0:
                return index + 1
    return len(structural_scan)


def _extract_functions(
    content: str,
    scan: str,
    structural_scan: str,
    lines: list[str],
    class_spans: tuple[tuple[int, int], ...],
    opaque_depths: list[int],
) -> tuple[ParsedFunction, ...]:
    """Collect every top-level `function` declaration and `const`/`let` arrow function.

    Declarations are found in `scan`. Each signature is then read with the same literal-aware
    helpers class and interface methods use (`_read_signature`): the parameter list's extent, the
    commas between parameters, and the end of the return type are decided on `structural_scan`,
    while every piece of text is sliced from `content`.

    Args:
        content: The original, unmodified file content.
        scan: `content` with comments blanked out.
        structural_scan: `scan` with string, template, and regex literals masked.
        lines: `content` split into lines.
        class_spans: Class body spans already found by `_extract_classes`, to exclude methods.
        opaque_depths: Opaque brace depth at every source position.

    Returns:
        Every free function found, in source order.
    """
    functions: list[ParsedFunction] = []

    for match in _FUNCTION_PATTERN.finditer(scan):
        if opaque_depths[match.start()] != 0 or _inside_any(match.start(), class_spans):
            continue
        params_open = _function_params_open(structural_scan, match.end())
        parameters, return_type = _read_signature(content, structural_scan, params_open)
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
        if (
            opaque_depths[match.start()] != 0
            or _inside_any(match.start(), class_spans)
            or not _is_arrow(structural_scan, match)
        ):
            continue
        params_open = match.end() - 1
        parameters, return_type = _read_signature(content, structural_scan, params_open)
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

    return tuple(sorted(functions, key=lambda function: function.line_number))


def _function_params_open(structural_scan: str, name_end: int) -> int:
    """Return the index of the `(` that opens a `function` declaration's parameter list.

    Type parameters after the name are skipped, so a `(` inside one -- as in
    `function f<T extends (x: number) => void>(a: T)` -- is not mistaken for the parameter list.
    The `>` of an arrow `=>` does not close a type-parameter list. If no balanced `<...>` follows
    the name, the search simply starts right after the name.

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        name_end: Index just after the function's name.

    Returns:
        The index of the first `(` at or after the end of the type parameters, or -1 if there
        is none.
    """
    index = _skip_whitespace(structural_scan, name_end, len(structural_scan))
    if index < len(structural_scan) and structural_scan[index] == "<":
        angle = 0
        for position in range(index, len(structural_scan)):
            character = structural_scan[position]
            if character == "<":
                angle += 1
            elif character == ">" and structural_scan[position - 1] != "=":
                angle -= 1
                if angle == 0:
                    index = position + 1
                    break
    return structural_scan.find("(", index)


def _is_arrow(structural_scan: str, match: re.Match[str]) -> bool:
    """Confirm that an `_ARROW_PATTERN` match is really an arrow function, not a plain call.

    `_ARROW_PATTERN` matches the prefix of both `const f = (x) => ...` and `const f = someCall(x);`
    -- only inspecting what follows the parameter list's closing `)` tells them apart. It is an
    arrow function exactly when the parameter list and its optional `: ReturnType` annotation (read
    by `_return_type_span`, on the literal-masked scan) are followed by `=>` on the same line. So a
    `)`, `;`, or `=>` inside a string literal type or a function type cannot change the answer, and
    neither can a `;` inside an object return type.

    Args:
        structural_scan: `content` with comments blanked and literals masked.
        match: An `_ARROW_PATTERN` match.

    Returns:
        True if `=>` follows the parameter list (and any `: ReturnType` annotation) without an
        intervening line break.
    """
    params_open = match.end() - 1
    params_close = find_matching_paren(structural_scan, params_open)
    span = _return_type_span(structural_scan, params_close)
    if span is not None:
        return structural_scan.startswith("=>", span[1])
    arrow_index = params_close + 1
    while arrow_index < len(structural_scan) and structural_scan[arrow_index] in " \t":
        arrow_index += 1
    return structural_scan.startswith("=>", arrow_index)


def _inside_any(index: int, spans: tuple[tuple[int, int], ...]) -> bool:
    """Report whether `index` falls inside any of `spans`.

    Args:
        index: A character offset into `scan`.
        spans: `(start, end)` spans to check against.

    Returns:
        True if `index` falls inside at least one span.
    """
    return any(start <= index < end for start, end in spans)


def _extract_simple(
    content: str, scan: str, pattern: re.Pattern[str], opaque_depths: list[int]
) -> dict[str, int]:
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
        match["name"]: line_number_at(content, match.start())
        for match in pattern.finditer(scan)
        if opaque_depths[match.start()] == 0
    }


def _extract_const_let_var(
    content: str, scan: str, *, exclude: set[str], opaque_depths: list[int]
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
        if opaque_depths[match.start()] != 0:
            continue
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
    interface_declarations: tuple[ParsedInterface, ...],
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
        ParsedSymbol(name=method.name, kind=SymbolKind.METHOD, line_number=method.line_number)
        for interface in interface_declarations
        for method in interface.methods
    )
    symbols.extend(
        ParsedSymbol(name=prop.name, kind=SymbolKind.PROPERTY, line_number=prop.line_number)
        for interface in interface_declarations
        for prop in interface.properties
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
