"""Structural symbol extractor: the first concrete `SymbolExtractor` implementation.

`StructuralSymbolExtractor` derives a file's `ExtractedSymbol` entries directly from its
already-parsed `parsers.base.ParseResult`: classes come from `parse_result.classes`, methods
from each class's own `methods`, top-level functions from `parse_result.functions`, and
constants from the `SymbolKind.CONSTANT`-kind entries in `parse_result.symbols`. It performs no
scope resolution, no cross-file analysis, no deduplication, and no naming heuristics; see
`SymbolExtractor`'s own docstring in `base.py` for what is deliberately out of scope.

Output order is fixed: all classes, then all methods (grouped by owning class, in class-then-
method order), then all top-level functions, then all constants. Source order is preserved
within each group and duplicates are never merged, matching the precedent set by
`StructuralImportExtractor`.

A `SymbolKind.CONSTANT` entry is passed through exactly as the parser produced it. Some of the
frozen parsers that emit this kind (`GoParser`, `RustParser`, `TypeScriptParser`) do not
actually restrict it to true top-level/module scope -- despite each parser's own docstring
claiming otherwise -- so a `CONSTANT`-kind symbol may in practice originate from a function
body, a method body, or (for Rust) an `impl` block. This extractor does not attempt to detect
or correct that: doing so would require scope information `parsers.base.ParsedSymbol` does not
carry, and would mean re-deriving parser-layer behavior this Port does not own. See
`docs/extractor_symbols_summary.md` for the full account of this known limitation.
"""

from src.extractors.symbols.base import (
    ExtractedSymbol,
    ExtractedSymbolKind,
    SymbolExtractionResult,
    SymbolExtractor,
    build_qualified_name,
    require_successful_parse,
)
from src.parsers.base import ParsedClass, ParsedFunction, ParsedSymbol, ParseResult, SymbolKind


class StructuralSymbolExtractor(SymbolExtractor):
    """Maps a file's already-parsed classes, methods, functions, and constants onto
    `ExtractedSymbol` values, one for one.

    Stateless and dependency-free: a single instance handles `ParseResult`s from every one of
    the five existing `Parser` implementations, since each already normalizes its own language's
    constructs into `parsers.base.ParsedClass`/`ParsedFunction`/`ParsedSymbol` before this
    extractor ever sees them.
    """

    def extract(self, parse_result: ParseResult) -> SymbolExtractionResult:
        """Extract one `ExtractedSymbol` per class, method, top-level function, and constant.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `ExtractedSymbol` entries: all classes, then
            all methods, then all top-level functions, then all constants, in that fixed order,
            with source order preserved within each group and duplicates included. Empty when
            the file has none of the four.

        Raises:
            ValidationError: If `parse_result.succeeded` is False.
        """
        require_successful_parse(parse_result)

        classes = tuple(
            _class_to_symbol(parse_result.relative_path, cls) for cls in parse_result.classes
        )
        methods = tuple(
            _method_to_symbol(parse_result.relative_path, cls, method)
            for cls in parse_result.classes
            for method in cls.methods
        )
        functions = tuple(
            _function_to_symbol(parse_result.relative_path, function)
            for function in parse_result.functions
        )
        constants = tuple(
            _constant_to_symbol(parse_result.relative_path, symbol)
            for symbol in parse_result.symbols
            if symbol.kind == SymbolKind.CONSTANT
        )

        return SymbolExtractionResult.ok(
            relative_path=parse_result.relative_path,
            symbols=classes + methods + functions + constants,
        )


def _class_to_symbol(relative_path: str, cls: ParsedClass) -> ExtractedSymbol:
    """Copy one `ParsedClass`'s fields onto an `ExtractedSymbol`, verbatim.

    Args:
        relative_path: The file the class was found in.
        cls: The parser's own already-normalized record of the class.

    Returns:
        An `ExtractedSymbol` of kind `CLASS`, unowned.
    """
    return ExtractedSymbol(
        qualified_name=build_qualified_name(relative_path=relative_path, name=cls.name),
        name=cls.name,
        kind=ExtractedSymbolKind.CLASS,
        relative_path=relative_path,
        line_number=cls.line_number,
    )


def _method_to_symbol(
    relative_path: str, cls: ParsedClass, method: ParsedFunction
) -> ExtractedSymbol:
    """Copy one method's fields onto an `ExtractedSymbol`, qualified by its owning class.

    Args:
        relative_path: The file the method was found in.
        cls: The class the method was found on.
        method: The parser's own already-normalized record of the method.

    Returns:
        An `ExtractedSymbol` of kind `METHOD`, owned by `cls.name`.
    """
    return ExtractedSymbol(
        qualified_name=build_qualified_name(
            relative_path=relative_path, name=method.name, owner=cls.name
        ),
        name=method.name,
        kind=ExtractedSymbolKind.METHOD,
        relative_path=relative_path,
        line_number=method.line_number,
    )


def _function_to_symbol(relative_path: str, function: ParsedFunction) -> ExtractedSymbol:
    """Copy one top-level function's fields onto an `ExtractedSymbol`, verbatim.

    Args:
        relative_path: The file the function was found in.
        function: The parser's own already-normalized record of the function.

    Returns:
        An `ExtractedSymbol` of kind `FUNCTION`, unowned.
    """
    return ExtractedSymbol(
        qualified_name=build_qualified_name(relative_path=relative_path, name=function.name),
        name=function.name,
        kind=ExtractedSymbolKind.FUNCTION,
        relative_path=relative_path,
        line_number=function.line_number,
    )


def _constant_to_symbol(relative_path: str, symbol: ParsedSymbol) -> ExtractedSymbol:
    """Copy one `SymbolKind.CONSTANT`-kind entry's fields onto an `ExtractedSymbol`, verbatim.

    Args:
        relative_path: The file the constant was found in.
        symbol: The parser's own already-normalized record of the constant, taken from
            `parse_result.symbols`. Passed through exactly as produced -- see this module's own
            docstring for the known cross-language scope limitation this implies.

    Returns:
        An `ExtractedSymbol` of kind `CONSTANT`, unowned.
    """
    return ExtractedSymbol(
        qualified_name=build_qualified_name(relative_path=relative_path, name=symbol.name),
        name=symbol.name,
        kind=ExtractedSymbolKind.CONSTANT,
        relative_path=relative_path,
        line_number=symbol.line_number,
    )
