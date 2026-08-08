"""Parser-layer Port, outcome DTO, and parsed-construct DTOs.

`python/parser.py`, `rust/parser.py`, `go/parser.py`, `typescript/parser.py`, and
`cpp/parser.py` each implement `Parser` for one `SourceLanguage` value, exposing the identical
public interface defined here: a `language` property, a `supports(relative_path)` extension
check, and a `parse(*, relative_path, content)` method.

`parse` is synchronous, not `async`, unlike `collectors.base.Collector.collect`. It performs no
I/O of its own -- the caller reads the file (via `collectors`/`repository`) and passes the
already-decoded `content` in -- so parsing is pure, in-memory, CPU-bound work, matching the same
sync/async split `repository.base.WorkspaceManager`'s docstring draws between local bookkeeping
and actual network or subprocess I/O. Taking `content` as a plain argument rather than a
filesystem path also keeps every `Parser` trivially constructible with zero arguments and easy to
substitute in tests or behind a DI container, with no hidden file-access side effect to mock out.

Like `collectors.base.Collector.collect`, `parse` reports failure (e.g. a syntax error) through
the returned `ParseResult` rather than raising -- a single file may legitimately fail to parse
without that being exceptional at the level of a whole-repository scan. The one exception this
package's Port raises, `core.exceptions.ValidationError`, is reused rather than a new
package-specific class being introduced, and is reserved for a blank `relative_path` argument: a
violation of `parse`'s basic contract, not a fact discovered about the file's content itself --
the same principle `collectors.base` follows for its own `require_source` check.

`PythonParser` delegates to the standard library `ast` module, which gives it an exact, always-
correct grammar for free. The other four languages have no such zero-dependency option available,
so `RustParser`, `GoParser`, `TypeScriptParser`, and `CppParser` instead use a lightweight,
regular-expression-based structural scan: enough to reliably recognize each language's common,
conventionally-formatted declaration forms, without the size and complexity of embedding a real
compiler front end for four different grammars. `strip_c_style_comments`, `find_matching_brace`,
and `line_number_at` below are the shared low-level scanning primitives all four of them build on
-- each is generic to any `//`/`/* */`-commented, brace-delimited language, so it lives here once
rather than being duplicated four times.
"""

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto

from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage


class SymbolKind(StrEnum):
    """The kind of a single entry in a `ParseResult.symbols` table.

    `symbols` is a flat, unified listing of every named construct a `Parser` found defined in a
    file -- a superset of `modules`, `classes`, and `functions`, plus constructs none of those
    three more specific fields has room for (variables, constants, interfaces, structs, enums,
    traits, type aliases, namespaces). Downstream consumers that just want "every named thing in
    this file, with its kind and location" can read `symbols` alone rather than reassembling one
    from `modules` + `classes` + `functions` themselves.
    """

    MODULE = auto()
    NAMESPACE = auto()
    CLASS = auto()
    STRUCT = auto()
    INTERFACE = auto()
    TRAIT = auto()
    ENUM = auto()
    TYPE_ALIAS = auto()
    FUNCTION = auto()
    METHOD = auto()
    VARIABLE = auto()
    CONSTANT = auto()


@dataclass(frozen=True, slots=True)
class ParsedImport:
    """A single import (or `use`/`include`/`require`) statement found in a file.

    Attributes:
        module: The imported module, path, or header, exactly as it identifies the thing being
            imported (e.g. `"os.path"`, `"crate::foo::Bar"`, `"./widgets"`, `"<vector>"`).
        imported_names: Specific names pulled from `module`, if the language's import form names
            them individually (e.g. Python's `from x import a, b`, TypeScript's
            `import { a, b } from "x"`). Empty when the statement imports the module as a whole.
        alias: The local alias the import is bound to, if the statement renames it (e.g. Python's
            `as`, Rust's `as`, TypeScript's `as`). None when no alias is used.
        is_relative: Whether `module` refers to another file within the same project (a relative
            or local path) rather than an external package, crate, or system library.
        line_number: 1-indexed line the statement starts on. 0 if unknown.
    """

    module: str
    imported_names: tuple[str, ...] = ()
    alias: str | None = None
    is_relative: bool = False
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class ParsedExport:
    """A single name a file explicitly makes available to importers.

    What counts as "exported" is language-specific: Python's `__all__` entries, TypeScript's
    `export`-prefixed declarations, Go's capitalized top-level identifiers, or a C++20 module's
    `export`-prefixed declarations. Languages with no such concept (plain C++ without modules)
    simply produce no `ParsedExport` entries.

    Attributes:
        name: The exported name.
        line_number: 1-indexed line the export is declared on. 0 if unknown.
    """

    name: str
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class ParsedFunction:
    """A single function or method found in a file.

    Attributes:
        name: The function's name.
        parameters: Each parameter as written, e.g. `"x"`, `"x: int"`, `"*args"` -- rendered as
            source text rather than split into separate name/type/default fields, since the
            exact shape of a parameter (variadic, keyword-only, defaulted, destructured) varies
            too much across these five languages for one common structure to hold losslessly.
        return_type: The declared return type, as written, if any.
        is_async: Whether the function is declared `async`.
        is_method: Whether this function was found inside a class/struct/impl body rather than
            at module or namespace scope.
        decorators: Decorators, attributes, or annotations attached to the function, as written
            (e.g. Python's `@staticmethod`, Rust's `#[test]`).
        docstring: The function's documentation comment or docstring, if present and directly
            attached.
        line_number: 1-indexed line the function is declared on. 0 if unknown.
    """

    name: str
    parameters: tuple[str, ...] = ()
    return_type: str | None = None
    is_async: bool = False
    is_method: bool = False
    decorators: tuple[str, ...] = ()
    docstring: str | None = None
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class ParsedClass:
    """A single class-like type found in a file.

    "Class-like" is intentionally broad: it covers Python/TypeScript classes, Rust and Go/C++
    structs (paired with their `impl`/method-receiver/in-body methods), and TypeScript
    interfaces are represented as `SymbolKind.INTERFACE` symbols instead, since an interface has
    no method bodies of its own to collect.

    Attributes:
        name: The class's name.
        base_classes: Base classes, parent interfaces, or implemented traits, as written.
        methods: Functions found attached to this class, as `ParsedFunction` entries with
            `is_method=True`.
        decorators: Decorators or attributes attached to the class, as written.
        docstring: The class's documentation comment or docstring, if present and directly
            attached.
        line_number: 1-indexed line the class is declared on. 0 if unknown.
    """

    name: str
    base_classes: tuple[str, ...] = ()
    methods: tuple[ParsedFunction, ...] = ()
    decorators: tuple[str, ...] = ()
    docstring: str | None = None
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class ParsedModule:
    """A nested module, package clause, or namespace declared within a file.

    This is distinct from the file's own identity as a module (which `FileMetadata` and
    `ParseResult.language`/`relative_path` already describe). It exists for languages that let
    one file declare an inner module boundary of its own: Rust's `mod foo { ... }`, Go's leading
    `package foo` clause, TypeScript's `namespace`/`module` blocks, and C++'s `namespace`
    blocks. Python has no equivalent construct, so `PythonParser` never produces one.

    Attributes:
        name: The module's, package's, or namespace's name.
        line_number: 1-indexed line the declaration starts on. 0 if unknown.
    """

    name: str
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class ParsedSymbol:
    """A single entry in a file's flat symbol table.

    See `SymbolKind` for why this exists alongside `ParseResult.modules`/`classes`/`functions`
    rather than replacing them.

    Attributes:
        name: The symbol's name.
        kind: What kind of construct this symbol is.
        line_number: 1-indexed line the symbol is declared on. 0 if unknown.
    """

    name: str
    kind: SymbolKind
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class FileMetadata:
    """Metadata about a file, independent of its parsed structural content.

    Attributes:
        relative_path: Path of the file relative to its repository root, exactly as passed to
            `Parser.parse`.
        language: Programming language `Parser.parse` determined the content to be.
        size_bytes: Size of `content`, in bytes, encoded as UTF-8.
        line_count: Number of lines in `content`.
        content_hash: SHA-256 hex digest of `content`, encoded as UTF-8. Lets a later phase
            detect whether a file's content changed without re-parsing it.
    """

    relative_path: str
    language: SourceLanguage
    size_bytes: int
    line_count: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Outcome of a single `Parser.parse` call.

    Attributes:
        relative_path: The file that was parsed, exactly as passed to `parse`.
        succeeded: Whether the parse attempt completed successfully.
        language: Programming language the file was parsed as.
        metadata: File metadata, always present when `succeeded` is True and always None when
            `succeeded` is False.
        modules: Nested module/namespace declarations found in the file. Always empty when
            `succeeded` is False.
        classes: Class-like types found in the file. Always empty when `succeeded` is False.
        functions: Free functions found in the file (methods live on their owning `ParsedClass`
            instead). Always empty when `succeeded` is False.
        imports: Import statements found in the file. Always empty when `succeeded` is False.
        exports: Exported names found in the file. Always empty when `succeeded` is False.
        symbols: Every named construct found in the file, as a flat table. Always empty when
            `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    language: SourceLanguage = SourceLanguage.UNKNOWN
    metadata: FileMetadata | None = None
    modules: tuple[ParsedModule, ...] = ()
    classes: tuple[ParsedClass, ...] = ()
    functions: tuple[ParsedFunction, ...] = ()
    imports: tuple[ParsedImport, ...] = ()
    exports: tuple[ParsedExport, ...] = ()
    symbols: tuple[ParsedSymbol, ...] = ()
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `metadata`, the parsed-content fields, and `error_message`
        are all consistent with one another.

        Raises:
            ValidationError: If a successful result is missing `metadata` or carries an error
                message, or a failed result carries `metadata`, any parsed content, or no error
                message.
        """
        if self.succeeded:
            if self.error_message is not None:
                raise ValidationError(
                    "ParseResult: error_message must be None when succeeded is True"
                )
            if self.metadata is None:
                raise ValidationError("ParseResult: metadata is required when succeeded is True")
        else:
            if self.error_message is None:
                raise ValidationError(
                    "ParseResult: error_message is required when succeeded is False"
                )
            if self.metadata is not None:
                raise ValidationError("ParseResult: metadata must be None when succeeded is False")
            if (
                self.modules
                or self.classes
                or self.functions
                or self.imports
                or self.exports
                or self.symbols
            ):
                raise ValidationError(
                    "ParseResult: parsed content must be empty when succeeded is False"
                )

    @classmethod
    def ok(
        cls,
        *,
        relative_path: str,
        language: SourceLanguage,
        metadata: FileMetadata,
        modules: Sequence[ParsedModule] = (),
        classes: Sequence[ParsedClass] = (),
        functions: Sequence[ParsedFunction] = (),
        imports: Sequence[ParsedImport] = (),
        exports: Sequence[ParsedExport] = (),
        symbols: Sequence[ParsedSymbol] = (),
    ) -> "ParseResult":
        """Build a successful result.

        Args:
            relative_path: The file that was parsed.
            language: Programming language the file was parsed as.
            metadata: File metadata computed for the file.
            modules: Nested module/namespace declarations found, possibly empty.
            classes: Class-like types found, possibly empty.
            functions: Free functions found, possibly empty.
            imports: Import statements found, possibly empty.
            exports: Exported names found, possibly empty.
            symbols: Every named construct found, as a flat table, possibly empty.

        Returns:
            A `ParseResult` with `succeeded=True`.
        """
        return cls(
            relative_path=relative_path,
            succeeded=True,
            language=language,
            metadata=metadata,
            modules=tuple(modules),
            classes=tuple(classes),
            functions=tuple(functions),
            imports=tuple(imports),
            exports=tuple(exports),
            symbols=tuple(symbols),
        )

    @classmethod
    def failed(
        cls, *, relative_path: str, language: SourceLanguage, error_message: str
    ) -> "ParseResult":
        """Build a failed result.

        Args:
            relative_path: The file that parsing was attempted against.
            language: Programming language the file was expected to be.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `ParseResult` with `succeeded=False`.
        """
        return cls(
            relative_path=relative_path,
            succeeded=False,
            language=language,
            error_message=error_message,
        )


class Parser(ABC):
    """Extracts structural information from a single file's already-read source content.

    A `Parser` decides *what is structurally present* in one file's `content` -- it does not
    read that content from disk itself (see `src.collectors`/`src.repository`) nor persist the
    result (see the future `storage` layer) -- both are separate, already- or not-yet-scoped
    concerns belonging to other layers.
    """

    @property
    @abstractmethod
    def language(self) -> SourceLanguage:
        """The `SourceLanguage` this parser produces `ParseResult` entries for."""
        ...

    @abstractmethod
    def supports(self, relative_path: str) -> bool:
        """Report whether this parser claims files at `relative_path`.

        Args:
            relative_path: Path of the candidate file, typically relative to a repository root.
                Only its extension is inspected; the file need not exist.

        Returns:
            True if `relative_path`'s extension is one this parser handles.
        """
        ...

    @abstractmethod
    def parse(self, *, relative_path: str, content: str) -> ParseResult:
        """Parse `content`, sourced from `relative_path`, into a `ParseResult`.

        Args:
            relative_path: Path of the file `content` was read from, typically relative to a
                repository root. Used only as a label on the returned result and, for languages
                whose grammar depends on it, is not itself re-read from disk.
            content: The file's full text content, already decoded.

        Returns:
            A successful result carrying every construct found, or a failed result carrying an
            explanation, if `content` cannot be parsed as this parser's language (e.g. a syntax
            error).

        Raises:
            ValidationError: If `relative_path` is blank.
        """
        ...


def require_relative_path(relative_path: str) -> str:
    """Validate that `relative_path` is non-blank.

    Every `Parser.parse` implementation calls this first, so a caller error (an empty or
    whitespace-only `relative_path`) is reported the same way -- as an immediate
    `ValidationError` -- across every language.

    Args:
        relative_path: The raw `relative_path` argument passed to `parse`.

    Returns:
        `relative_path`, unchanged.

    Raises:
        ValidationError: If `relative_path` is blank.
    """
    if not relative_path.strip():
        raise ValidationError("relative_path must not be empty")
    return relative_path


def has_extension(relative_path: str, extensions: Sequence[str]) -> bool:
    """Report whether `relative_path` ends with one of `extensions`, case-insensitively.

    Shared by every language's `supports` implementation.

    Args:
        relative_path: Path of the candidate file.
        extensions: Extensions to match against, each including its leading dot (e.g. `".py"`).

    Returns:
        True if `relative_path`, lower-cased, ends with one of `extensions`.
    """
    lowered = relative_path.lower()
    return any(lowered.endswith(extension) for extension in extensions)


def compute_content_hash(content: str) -> str:
    """Compute the SHA-256 hex digest of `content`, encoded as UTF-8.

    Args:
        content: The file's full text content.

    Returns:
        A 64-character lowercase hex digest.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_file_metadata(
    *, relative_path: str, language: SourceLanguage, content: str
) -> FileMetadata:
    """Build the `FileMetadata` common to every language's `parse` implementation.

    Args:
        relative_path: Path of the file `content` was read from.
        language: Programming language `content` was parsed as.
        content: The file's full text content.

    Returns:
        Metadata describing `content`, independent of its parsed structural content.
    """
    return FileMetadata(
        relative_path=relative_path,
        language=language,
        size_bytes=len(content.encode("utf-8")),
        line_count=len(content.splitlines()),
        content_hash=compute_content_hash(content),
    )


def line_number_at(content: str, index: int) -> int:
    """Compute the 1-indexed line number of a character offset within `content`.

    Args:
        content: The full text `index` is an offset into.
        index: A character offset within `content`.

    Returns:
        The 1-indexed line number containing `index`.
    """
    return content.count("\n", 0, index) + 1


def _find_matching(content: str, open_index: int, open_char: str, close_char: str) -> int:
    """Find the index of the `close_char` that closes the `open_char` at `open_index`.

    Shared implementation behind `find_matching_brace` and `find_matching_paren`.

    Args:
        content: The full text to scan.
        open_index: Index of an opening delimiter (`content[open_index]` must be `open_char`).
        open_char: The opening delimiter character.
        close_char: The closing delimiter character.

    Returns:
        Index of the matching closing delimiter, accounting for nesting, or `len(content)` if it
        is never closed (malformed or truncated input).
    """
    depth = 0
    for index in range(open_index, len(content)):
        character = content[index]
        if character == open_char:
            depth += 1
        elif character == close_char:
            depth -= 1
            if depth == 0:
                return index
    return len(content)


def find_matching_brace(content: str, open_index: int) -> int:
    """Find the index of the `}` that closes the `{` at `open_index`.

    Args:
        content: The full text to scan.
        open_index: Index of an opening brace (`content[open_index]` must be `"{"`).

    Returns:
        Index of the matching closing brace, accounting for nested `{ }` pairs in between, or
        `len(content)` if the brace is never closed (malformed or truncated input).
    """
    return _find_matching(content, open_index, "{", "}")


def find_matching_paren(content: str, open_index: int) -> int:
    """Find the index of the `)` that closes the `(` at `open_index`.

    Used to extract a full parameter list even when it contains nested parentheses, e.g. a
    function-typed parameter such as Go's `f func(int) string` or a Rust closure bound like
    `Fn(i32) -> i32`, where a naive "up to the next `)`" scan would stop too early.

    Args:
        content: The full text to scan.
        open_index: Index of an opening parenthesis (`content[open_index]` must be `"("`).

    Returns:
        Index of the matching closing parenthesis, accounting for nested `( )` pairs in between,
        or `len(content)` if it is never closed (malformed or truncated input).
    """
    return _find_matching(content, open_index, "(", ")")


def split_top_level(text: str, delimiter: str = ",") -> tuple[str, ...]:
    """Split `text` on `delimiter`, ignoring any occurrence nested inside `()`, `[]`, or `{}`.

    Used to split a parameter or argument list into individual entries without breaking on a
    delimiter that is actually part of a nested type or expression -- e.g. Go's
    `f func(int, string), x int` must split into exactly two parameters, not three.

    Args:
        text: The text to split, e.g. the contents of a parameter list.
        delimiter: The single character to split on. Defaults to a comma.

    Returns:
        Each segment of `text` between top-level occurrences of `delimiter`, stripped of
        surrounding whitespace. Empty (all-whitespace) segments are dropped, so splitting an
        empty or whitespace-only `text` yields an empty tuple.
    """
    segments: list[str] = []
    depth = 0
    current: list[str] = []
    for character in text:
        if character in "([{":
            depth += 1
            current.append(character)
        elif character in ")]}":
            depth -= 1
            current.append(character)
        elif character == delimiter and depth == 0:
            segments.append("".join(current))
            current = []
        else:
            current.append(character)
    segments.append("".join(current))
    return tuple(segment.strip() for segment in segments if segment.strip())


def is_top_level_of_span(scan: str, span_start: int, index: int) -> bool:
    """Report whether `index` sits at brace depth 0 relative to `span_start`.

    Used when scanning a block's body (e.g. a class body) for its direct members: a member's own
    declaration sits at depth 0 relative to the block's opening brace, while a statement inside
    one of that block's own methods sits deeper, nested inside that method's own `{ }`.
    Comparing depth this way is what keeps a plain call statement inside a method's body (e.g.
    `doSomething(a, b);`) from being mistaken for a sibling method declaration.

    Args:
        scan: The text `span_start` and `index` are offsets into (typically comment-blanked).
        span_start: Index immediately after the block's own opening brace.
        index: The offset to test.

    Returns:
        True if the net count of `{` minus `}` between `span_start` and `index` is zero.
    """
    segment = scan[span_start:index]
    return segment.count("{") == segment.count("}")


def leading_comment_lines(
    lines: Sequence[str], declaration_line: int, *, prefix: str
) -> str | None:
    """Collect consecutive same-prefix comment lines immediately above a declaration.

    Shared by `RustParser` and `CppParser`, which both use a repeated line-comment marker
    (Rust's `///`, C++'s common `///` Doxygen convention) for a declaration's documentation,
    rather than TypeScript's single `/** ... */` block form.

    Args:
        lines: The file's content, split into lines (as from `str.splitlines()`).
        declaration_line: 1-indexed line number of the declaration.
        prefix: The line-comment marker each doc-comment line must start with, after leading
            whitespace, e.g. `"///"`.

    Returns:
        The collected comment text, one input line per output line with `prefix` and one
        following space (if present) stripped, in original top-to-bottom order -- or None if no
        such comment line immediately precedes `declaration_line`.
    """
    collected: list[str] = []
    index = declaration_line - 2  # 0-indexed line directly above the 1-indexed declaration line
    while index >= 0:
        stripped = lines[index].strip()
        if not stripped.startswith(prefix):
            break
        collected.append(stripped[len(prefix) :].removeprefix(" "))
        index -= 1
    if not collected:
        return None
    collected.reverse()
    return "\n".join(collected)


def strip_c_style_comments(content: str) -> str:
    """Blank out `//` line comments and `/* ... */` block comments in `content`.

    Every comment character is replaced with a space, and every newline is preserved exactly --
    so the result has the same length and the same line/column layout as `content`, and every
    offset computed against it remains valid against the original via `line_number_at`. This
    keeps a language's structural regexes (matching `class`, `fn`, `struct`, and so on) from
    firing on lookalike text that only appears inside a comment.

    String and character literals are not specially recognized, so a literal containing `//` or
    `/*` (for example inside a Rust raw string or a TypeScript template literal) can in rare
    cases be mistaken for the start of a comment. This is an accepted, bounded limitation of a
    lightweight structural scan, not a full lexer.

    Args:
        content: The full source text to scan.

    Returns:
        `content` with every comment's characters (other than newlines) replaced by spaces.
    """
    result: list[str] = []
    index = 0
    length = len(content)
    in_block_comment = False
    while index < length:
        if in_block_comment:
            if content[index : index + 2] == "*/":
                result.append("  ")
                index += 2
                in_block_comment = False
            elif content[index] == "\n":
                result.append("\n")
                index += 1
            else:
                result.append(" ")
                index += 1
            continue
        if content[index : index + 2] == "/*":
            result.append("  ")
            index += 2
            in_block_comment = True
            continue
        if content[index : index + 2] == "//":
            while index < length and content[index] != "\n":
                result.append(" ")
                index += 1
            continue
        result.append(content[index])
        index += 1
    return "".join(result)
