"""Structural AST extractor: the first concrete `AstExtractor` implementation.

`StructuralAstExtractor` derives a file's `AstMetadata` directly from its already-parsed
`parsers.base.ParseResult` -- eleven non-negative structural counts, nothing more. It performs
counting only: no quality judgment, no complexity scoring, no inference beyond arithmetic over
fields the parser layer already produced, no cross-file aggregation, and no module resolution;
see `AstExtractor`'s own docstring in `base.py` for what is deliberately out of scope.
"""

from src.extractors.ast.base import (
    AstExtractionResult,
    AstExtractor,
    AstMetadata,
    require_successful_parse,
)
from src.parsers.base import ParseResult


class StructuralAstExtractor(AstExtractor):
    """Maps a file's already-parsed structure onto eleven non-negative `AstMetadata` counts.

    Stateless and dependency-free: a single instance handles `ParseResult`s from every one of
    the five existing `Parser` implementations, since each already normalizes its own language's
    constructs into the same `ParseResult` shape before this extractor ever sees it.
    """

    def extract(self, parse_result: ParseResult) -> AstExtractionResult:
        """Extract structural counts for the file described by `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `AstMetadata` -- eleven counts derived
            directly from fields already present on `parse_result`. Every count is `0` for a
            field the file has none of; nothing is ever negative.

        Raises:
            ValidationError: If `parse_result.succeeded` is False.
        """
        require_successful_parse(parse_result)
        # Guaranteed non-None once `succeeded` is True -- see `ParseResult.metadata`'s own
        # docstring; `require_successful_parse` above is what makes this safe.
        assert parse_result.metadata is not None

        async_function_count = sum(
            1 for function in parse_result.functions if function.is_async
        ) + sum(
            1
            for cls in parse_result.classes
            for method in cls.methods
            if method.is_async
        )
        documented_class_count = sum(
            1 for cls in parse_result.classes if cls.docstring is not None
        )
        documented_function_count = sum(
            1 for function in parse_result.functions if function.docstring is not None
        ) + sum(
            1
            for cls in parse_result.classes
            for method in cls.methods
            if method.docstring is not None
        )

        metadata = AstMetadata(
            relative_path=parse_result.relative_path,
            class_count=len(parse_result.classes),
            function_count=len(parse_result.functions),
            method_count=sum(len(cls.methods) for cls in parse_result.classes),
            import_count=len(parse_result.imports),
            export_count=len(parse_result.exports),
            symbol_count=len(parse_result.symbols),
            module_count=len(parse_result.modules),
            async_function_count=async_function_count,
            documented_class_count=documented_class_count,
            documented_function_count=documented_function_count,
            line_count=parse_result.metadata.line_count,
        )
        return AstExtractionResult.ok(relative_path=parse_result.relative_path, metadata=metadata)
