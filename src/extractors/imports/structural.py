"""Structural import extractor: the first concrete `ImportExtractor` implementation.

`StructuralImportExtractor` derives a file's `DependencyEdge` entries directly from its
already-parsed `parsers.base.ParseResult.imports` -- a pure, total reshaping of data the parser
layer already produced. It performs no module-path resolution, no cross-language normalization,
no filtering, and no deduplication; see `ImportExtractor`'s own docstring in `base.py` for what
is deliberately out of scope.
"""

from src.extractors.imports.base import (
    DependencyEdge,
    ImportExtractionResult,
    ImportExtractor,
    require_successful_parse,
)
from src.parsers.base import ParsedImport, ParseResult


class StructuralImportExtractor(ImportExtractor):
    """Maps a file's already-parsed imports onto `DependencyEdge` values, one for one.

    Stateless and dependency-free: a single instance handles `ParseResult`s from every one of
    the five existing `Parser` implementations, since each already normalizes its own language's
    import syntax into `parsers.base.ParsedImport` before this extractor ever sees it.
    """

    def extract(self, parse_result: ParseResult) -> ImportExtractionResult:
        """Extract one `DependencyEdge` per import statement in `parse_result`.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying one `DependencyEdge` per entry in
            `parse_result.imports`, in the same order, duplicates included. Empty when the file
            has no imports.

        Raises:
            ValidationError: If `parse_result.succeeded` is False.
        """
        require_successful_parse(parse_result)
        edges = tuple(
            _to_edge(parse_result.relative_path, parsed_import)
            for parsed_import in parse_result.imports
        )
        return ImportExtractionResult.ok(relative_path=parse_result.relative_path, edges=edges)


def _to_edge(source_path: str, parsed_import: ParsedImport) -> DependencyEdge:
    """Copy one `ParsedImport`'s fields onto a `DependencyEdge`, verbatim.

    Args:
        source_path: The file the import statement was found in.
        parsed_import: The parser's own already-normalized record of the statement.

    Returns:
        A `DependencyEdge` carrying exactly `parsed_import`'s data -- no resolution, no
        normalization, no inference.
    """
    return DependencyEdge(
        source_path=source_path,
        target_module=parsed_import.module,
        imported_names=parsed_import.imported_names,
        alias=parsed_import.alias,
        is_internal=parsed_import.is_relative,
        line_number=parsed_import.line_number,
    )
