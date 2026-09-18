"""Structural interface extractor: the first concrete `InterfaceExtractor` implementation.

`StructuralInterfaceExtractor` derives a file's `ExtractedInterface` entries directly from its
already-parsed `parsers.base.ParseResult`, across two disjoint, mutually exclusive sources:
`SymbolKind.INTERFACE`/`SymbolKind.TRAIT` entries in `parse_result.symbols` (TypeScript/Go
`interface`, Rust `trait` -- languages that express interfaces as a distinct, language-native
construct), and `ParsedClass` entries in `parse_result.classes` whose `base_classes` names one of
Python's structural-typing base classes (a language that expresses them as an ordinary class).
The two sources never collide in practice: none of the five parsers ever emits
`SymbolKind.INTERFACE`/`TRAIT` for a Python construct, and none of the four non-Python parsers
ever populates `base_classes` with one of the locked Python spellings below -- so this extractor
performs no deduplication, no merge, and no priority ordering between them; the three groups are
simply concatenated.

The Python base-class match is a closed, exact-string-equality check against exactly
`{"ABC", "abc.ABC", "Protocol", "typing.Protocol"}` -- no fuzzy matching, no substring matching,
no import-alias resolution, and no additional spelling. A `@abstractmethod`-decorated method is
never, on its own, sufficient to classify a class as `InterfaceOrigin.ABSTRACT_CLASS`; only
`base_classes` is consulted. This is a locked scope decision, not an oversight -- see
`docs/extractor_interfaces_summary.md` for the discovery and lock history behind it.

Output order is fixed: all `LANGUAGE_INTERFACE` entries, then all `TRAIT` entries, then all
`ABSTRACT_CLASS` entries. Source order is preserved within each group and duplicates are never
merged, matching the precedent set by `StructuralSymbolExtractor`.

C++ pure-virtual classes are never recognized as `ABSTRACT_CLASS`: `parsers.base.ParsedFunction`
carries no field a pure-virtual method (`= 0`) could be derived from -- `CppParser` discards the
`virtual` keyword itself as prefix noise when building a method's parsed record -- and this
extractor does not re-scan source text to recover it. See `docs/extractor_interfaces_summary.md`
for the full account of this known limitation.
"""

from src.extractors.interfaces.base import (
    ExtractedInterface,
    InterfaceExtractionResult,
    InterfaceExtractor,
    InterfaceOrigin,
    require_successful_parse,
)
from src.parsers.base import ParsedClass, ParsedSymbol, ParseResult, SymbolKind

_PYTHON_ABC_PROTOCOL_BASES = ("ABC", "abc.ABC", "Protocol", "typing.Protocol")


class StructuralInterfaceExtractor(InterfaceExtractor):
    """Maps a file's already-parsed native interface/trait symbols and Python ABC/Protocol
    classes onto `ExtractedInterface` values.

    Stateless and dependency-free: a single instance handles `ParseResult`s from every one of
    the five existing `Parser` implementations, since each already normalizes its own language's
    constructs into `parsers.base.ParsedSymbol`/`ParsedClass` before this extractor ever sees
    them.
    """

    def extract(self, parse_result: ParseResult) -> InterfaceExtractionResult:
        """Extract one `ExtractedInterface` per native interface/trait symbol and per
        recognized Python ABC/Protocol class.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `ExtractedInterface` entries: all
            `LANGUAGE_INTERFACE` entries, then all `TRAIT` entries, then all `ABSTRACT_CLASS`
            entries, in that fixed order, with source order preserved within each group and
            duplicates included. Empty when the file has none of the three.

        Raises:
            ValidationError: If `parse_result.succeeded` is False.
        """
        require_successful_parse(parse_result)

        language_interfaces = tuple(
            _interface_symbol_to_interface(parse_result.relative_path, symbol)
            for symbol in parse_result.symbols
            if symbol.kind == SymbolKind.INTERFACE
        )
        traits = tuple(
            _trait_symbol_to_interface(parse_result.relative_path, symbol)
            for symbol in parse_result.symbols
            if symbol.kind == SymbolKind.TRAIT
        )
        abstract_classes = tuple(
            _class_to_interface(parse_result.relative_path, cls)
            for cls in parse_result.classes
            if _has_abc_or_protocol_base(cls)
        )

        return InterfaceExtractionResult.ok(
            relative_path=parse_result.relative_path,
            interfaces=language_interfaces + traits + abstract_classes,
        )


def _has_abc_or_protocol_base(cls: ParsedClass) -> bool:
    """Whether `cls` declares at least one of the four locked Python ABC/Protocol base-class
    spellings.

    Args:
        cls: The parser's own already-normalized record of the class.

    Returns:
        True if `cls.base_classes` contains one of `{"ABC", "abc.ABC", "Protocol",
        "typing.Protocol"}`, by exact string equality. False otherwise -- including when `cls`
        has an `@abstractmethod`-decorated method but no matching base class; that decorator is
        never, on its own, sufficient (see this module's own docstring).
    """
    return any(base in _PYTHON_ABC_PROTOCOL_BASES for base in cls.base_classes)


def _interface_symbol_to_interface(relative_path: str, symbol: ParsedSymbol) -> ExtractedInterface:
    """Copy one `SymbolKind.INTERFACE` symbol's fields onto an `ExtractedInterface`, verbatim.

    Args:
        relative_path: The file the symbol was found in.
        symbol: The parser's own already-normalized record of the symbol, taken from
            `parse_result.symbols`.

    Returns:
        An `ExtractedInterface` of origin `LANGUAGE_INTERFACE`, with empty
        `method_signatures`/`base_interfaces` -- `ParsedSymbol` carries neither.
    """
    return ExtractedInterface(
        name=symbol.name,
        origin=InterfaceOrigin.LANGUAGE_INTERFACE,
        relative_path=relative_path,
        line_number=symbol.line_number,
    )


def _trait_symbol_to_interface(relative_path: str, symbol: ParsedSymbol) -> ExtractedInterface:
    """Copy one `SymbolKind.TRAIT` symbol's fields onto an `ExtractedInterface`, verbatim.

    Args:
        relative_path: The file the symbol was found in.
        symbol: The parser's own already-normalized record of the symbol, taken from
            `parse_result.symbols`.

    Returns:
        An `ExtractedInterface` of origin `TRAIT`, with empty `method_signatures`/
        `base_interfaces` -- `ParsedSymbol` carries neither.
    """
    return ExtractedInterface(
        name=symbol.name,
        origin=InterfaceOrigin.TRAIT,
        relative_path=relative_path,
        line_number=symbol.line_number,
    )


def _class_to_interface(relative_path: str, cls: ParsedClass) -> ExtractedInterface:
    """Copy one recognized Python ABC/Protocol class's fields onto an `ExtractedInterface`.

    Args:
        relative_path: The file the class was found in.
        cls: The parser's own already-normalized record of the class, already confirmed by
            `_has_abc_or_protocol_base` to declare one of the locked base-class spellings.

    Returns:
        An `ExtractedInterface` of origin `ABSTRACT_CLASS`, with `method_signatures` set to
        `cls`'s method names and `base_interfaces` set to `cls.base_classes`, both verbatim.
    """
    return ExtractedInterface(
        name=cls.name,
        origin=InterfaceOrigin.ABSTRACT_CLASS,
        relative_path=relative_path,
        method_signatures=tuple(method.name for method in cls.methods),
        base_interfaces=cls.base_classes,
        line_number=cls.line_number,
    )
