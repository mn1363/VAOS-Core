"""Interface extractor Port: interface/protocol pattern extraction.

`InterfaceExtractor` turns a single file's `parsers.base.ParseResult` into a normalized list of
`ExtractedInterface` entries -- the file's interface-shaped declarations, regardless of which of
several source-language forms expressed it: a TypeScript `interface`, a Go `interface`, a Rust
`trait` (all reported by `src.parsers` as `SymbolKind.INTERFACE`/`SymbolKind.TRAIT` symbols), or
a Python abstract base class / `typing.Protocol` (reported as an ordinary `ParsedClass`, since
`src.parsers` does not special-case Python's structural-typing conventions). A concrete
implementation is expected to recognize the latter from `ParsedClass.base_classes` (e.g. a base
of `"ABC"`, `"abc.ABC"`, or `"Protocol"`) and `ParsedFunction.decorators` (`"abstractmethod"`) on
its methods, in addition to consuming the `SymbolKind.INTERFACE`/`SymbolKind.TRAIT` entries the
other languages already provide directly.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.parsers.base import ParseResult

_logger = get_logger("extractors.interfaces")


class InterfaceOrigin(StrEnum):
    """How an `ExtractedInterface` was expressed in its source language.

    Members are named for the source-level construct each covers, rather than a single generic
    "interface" label, since a downstream consumer may care which form it originally was (e.g. a
    Rust `trait` can be derived from; a TypeScript `interface` cannot be instantiated at all).

    Attributes:
        LANGUAGE_INTERFACE: A language-native `interface` declaration (TypeScript, Go).
        TRAIT: A Rust `trait` declaration.
        ABSTRACT_CLASS: A class recognized as structurally interface-like (e.g. a Python `ABC`
            subclass, a `typing.Protocol`, or a C++ class of pure-virtual methods).
    """

    LANGUAGE_INTERFACE = auto()
    TRAIT = auto()
    ABSTRACT_CLASS = auto()


@dataclass(frozen=True, slots=True)
class ExtractedInterface:
    """A single interface-shaped declaration found in a file.

    Attributes:
        name: The interface's name.
        origin: Which source-level construct this interface was expressed as.
        relative_path: Path of the file the interface was found in.
        method_signatures: The interface's declared method names, as written -- empty for a
            language-native `interface`/`trait` symbol, whose method signatures `src.parsers`
            does not currently expose beyond the symbol's own name (see `parsers.base.
            SymbolKind`); populated when `origin` is `ABSTRACT_CLASS`, whose methods a
            `ParsedClass` already carries in full.
        base_interfaces: Parent interfaces or traits this interface extends, as written.
        line_number: 1-indexed line the interface is declared on. 0 if unknown.
    """

    name: str
    origin: InterfaceOrigin
    relative_path: str
    method_signatures: tuple[str, ...] = ()
    base_interfaces: tuple[str, ...] = ()
    line_number: int = 0


@dataclass(frozen=True, slots=True)
class InterfaceExtractionResult:
    """Outcome of a single `InterfaceExtractor.extract` call.

    Attributes:
        relative_path: The file extraction was attempted against.
        succeeded: Whether extraction completed successfully.
        interfaces: The file's extracted interface-shaped declarations. Always empty when
            `succeeded` is False; may legitimately be empty when `succeeded` is True too (a file
            with no interfaces).
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    relative_path: str
    succeeded: bool
    interfaces: tuple[ExtractedInterface, ...] = ()
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `interfaces`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result carries an error message, or a failed
                result carries interfaces or no error message.
        """
        if self.succeeded and self.error_message is not None:
            raise ValidationError(
                "InterfaceExtractionResult: error_message must be None when succeeded is True"
            )
        if not self.succeeded and self.interfaces:
            raise ValidationError(
                "InterfaceExtractionResult: interfaces must be empty when succeeded is False"
            )
        if not self.succeeded and self.error_message is None:
            raise ValidationError(
                "InterfaceExtractionResult: error_message is required when succeeded is False"
            )

    @classmethod
    def ok(
        cls, *, relative_path: str, interfaces: Sequence[ExtractedInterface] = ()
    ) -> "InterfaceExtractionResult":
        """Build a successful result.

        Args:
            relative_path: The file that was extracted from.
            interfaces: Interface-shaped declarations found in the file, possibly empty.

        Returns:
            An `InterfaceExtractionResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, interfaces=tuple(interfaces))

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "InterfaceExtractionResult":
        """Build a failed result.

        Args:
            relative_path: The file that extraction was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            An `InterfaceExtractionResult` with `succeeded=False`.
        """
        _logger.debug("Interface extraction failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class InterfaceExtractor(ABC):
    """Extracts a single file's interface-shaped declarations from its already-parsed
    structure.

    A concrete implementation decides which of a file's parsed constructs are interface-shaped,
    across every source-language form `src.parsers` can produce (see module docstring); it does
    not decide whether an interface is well-designed or worth reusing -- see the future
    `analyzers` phase and `extractors.foundation`, respectively.
    """

    @abstractmethod
    def extract(self, parse_result: ParseResult) -> InterfaceExtractionResult:
        """Extract interface-shaped declarations for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `ExtractedInterface` entries, or a failed
            result carrying an explanation, if interfaces cannot be derived from `parse_result`.

        Raises:
            ValidationError: If `parse_result.succeeded` is False -- extraction requires a
                successfully parsed file.
        """
        ...


def require_successful_parse(parse_result: ParseResult) -> ParseResult:
    """Validate that `parse_result` represents a successful parse.

    Every `InterfaceExtractor.extract` implementation calls this first, so a caller error (a
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
            "cannot extract interfaces from a failed ParseResult",
            details={"relative_path": parse_result.relative_path},
        )
    return parse_result
