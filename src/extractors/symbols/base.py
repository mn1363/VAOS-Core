"""Symbol extractor Port: classes/functions/constants extraction.

`SymbolExtractor` turns a single file's `parsers.base.ParseResult` into a focused table of the
three construct kinds most relevant to reuse decisions -- classes, functions (including
methods), and constants -- as flat `ExtractedSymbol` entries carrying a fully-qualified name.
This is narrower than `parsers.base.ParseResult.symbols`, which is a complete table of every
named construct a `Parser` found (including modules, interfaces, and variables); a
`SymbolExtractor` filters and re-shapes that broader table for consumers that specifically want
classes, functions, and constants.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.parsers.base import ParseResult

_logger = get_logger("extractors.symbols")


class ExtractedSymbolKind(StrEnum):
    """The kind of construct a single `ExtractedSymbol` represents.

    A deliberately narrow subset of `parsers.base.SymbolKind` -- the three kinds this Port's
    contract (classes, functions, constants) is scoped to -- rather than the full construct
    taxonomy `parsers.base.SymbolKind` covers.
    """

    CLASS = auto()
    FUNCTION = auto()
    METHOD = auto()
    CONSTANT = auto()


@dataclass(frozen=True, slots=True)
class ExtractedSymbol:
    """A single class, function, method, or constant found in a file.

    Attributes:
        qualified_name: The symbol's name, qualified by its owning file and, for a method, its
            owning class (e.g. `"src/domain/entities.py::SourceRepository.mark_ready"`), so it
            remains unambiguous outside the context of any single `SymbolExtractionResult`. See
            `build_qualified_name`.
        name: The symbol's own, unqualified name.
        kind: What kind of construct this symbol is.
        relative_path: Path of the file the symbol was found in.
        line_number: 1-indexed line the symbol is declared on. 0 if unknown.
    """

    qualified_name: str
    name: str
    kind: ExtractedSymbolKind
    relative_path: str
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class SymbolExtractionResult:
    """Outcome of a single `SymbolExtractor.extract` call.

    Attributes:
        relative_path: The file extraction was attempted against.
        succeeded: Whether extraction completed successfully.
        symbols: The file's extracted classes, functions, and constants. Always empty when
            `succeeded` is False; may legitimately be empty when `succeeded` is True too.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    symbols: tuple[ExtractedSymbol, ...] = ()
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `symbols`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result carries an error message, or a failed
                result carries symbols or no error message.
        """
        if self.succeeded and self.error_message is not None:
            raise ValidationError(
                "SymbolExtractionResult: error_message must be None when succeeded is True"
            )
        if not self.succeeded and self.symbols:
            raise ValidationError(
                "SymbolExtractionResult: symbols must be empty when succeeded is False"
            )
        if not self.succeeded and self.error_message is None:
            raise ValidationError(
                "SymbolExtractionResult: error_message is required when succeeded is False"
            )

    @classmethod
    def ok(
        cls, *, relative_path: str, symbols: Sequence[ExtractedSymbol] = ()
    ) -> "SymbolExtractionResult":
        """Build a successful result.

        Args:
            relative_path: The file that was extracted from.
            symbols: Classes, functions, and constants found in the file, possibly empty.

        Returns:
            A `SymbolExtractionResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, symbols=tuple(symbols))

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "SymbolExtractionResult":
        """Build a failed result.

        Args:
            relative_path: The file that extraction was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `SymbolExtractionResult` with `succeeded=False`.
        """
        _logger.debug("Symbol extraction failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class SymbolExtractor(ABC):
    """Extracts a single file's classes, functions, and constants from its already-parsed
    structure.

    A concrete implementation decides which of a file's parsed constructs qualify as a class,
    function, method, or constant, and how to name each one unambiguously; it does not judge
    whether any of them is reusable (see `extractors.foundation`) or well-designed (see the
    future `analyzers` phase).
    """

    @abstractmethod
    def extract(self, parse_result: ParseResult) -> SymbolExtractionResult:
        """Extract classes, functions, and constants for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `ExtractedSymbol` entries, or a failed
            result carrying an explanation, if symbols cannot be derived from `parse_result`.

        Raises:
            ValidationError: If `parse_result.succeeded` is False -- extraction requires a
                successfully parsed file.
        """
        ...


def require_successful_parse(parse_result: ParseResult) -> ParseResult:
    """Validate that `parse_result` represents a successful parse.

    Every `SymbolExtractor.extract` implementation calls this first, so a caller error (a
    `ParseResult` with `succeeded=False`) is reported the same way -- as an immediate
    `ValidationError` -- across every implementation.

    Args:
        parse_result: The raw `parse_result` argument passed to `extract`.

    Returns:
        `parse_result`, unchanged.

    Raises:
        ValidationError: If `parse_result.succeeded` is False.
    """
    if not parse_result.succeeded:
        _logger.debug(
            "Rejected extraction from an unsuccessful parse of '%s'", parse_result.relative_path
        )
        raise ValidationError(
            "cannot extract symbols from a failed ParseResult",
            details={"relative_path": parse_result.relative_path},
        )
    return parse_result


def build_qualified_name(*, relative_path: str, name: str, owner: str | None = None) -> str:
    """Build the fully-qualified name for a symbol found at `relative_path`.

    Args:
        relative_path: Path of the file the symbol was found in.
        name: The symbol's own, unqualified name.
        owner: The name of the symbol's owning class, if it is a method. None for a
            free-standing class, function, or constant.

    Returns:
        `relative_path` joined to `name` with `"::"`, with `owner` interposed and joined to
        `name` with `"."` when given (e.g. `"a.py::Foo.bar"`), matching the format documented on
        `ExtractedSymbol.qualified_name`.
    """
    local_name = f"{owner}.{name}" if owner else name
    return f"{relative_path}::{local_name}"
