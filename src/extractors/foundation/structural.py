"""Structural foundation extractor: the first concrete `FoundationExtractor` implementation.

`StructuralFoundationExtractor` derives a file's `FoundationCandidate` entries directly from its
already-parsed `parsers.base.ParseResult`, mechanically and without judgment: one `CLASS`
candidate per entry in `parse_result.classes`, then one `FUNCTION` candidate per entry in
`parse_result.functions`. Methods are never emitted -- `FoundationCandidateKind` has no METHOD
member and `FoundationCandidate` has no owner field, so a method could not be represented
without inventing a new kind or a new identity rule. Constructs the parsers surface only as
`ParseResult.symbols` (TypeScript/Go interfaces, Rust traits and enums, type aliases) are never
`ParsedClass` entries, so they are never candidates either.

Every field is a direct copy or a single, exact predicate over data the frozen parser layer
already carries:

- `is_public` is export-list membership and nothing more: the candidate's name is present in
  `{export.name for export in parse_result.exports}`. `parse_result.exports` holds
  `ParsedExport` objects, not strings, so the comparison is against each export's `.name` --
  comparing a string directly against `parse_result.exports` is always False. No naming
  convention, underscore rule, capitalization rule, access modifier, or language-specific
  visibility rule is consulted, and there is no "unknown" state. A False value therefore means
  "not in the parser's export list", never "proven private": a Python file without `__all__`,
  and every ordinary (non-module) C++ file, produces False for every candidate.
- `has_docstring` is exactly `docstring is not None` -- never a truthiness check, so an empty
  docstring (an empty triple-quoted string in Python, a bare `///` in Rust or C++) still
  counts as documented.
- `signals` is always `()`. No closed signal vocabulary exists anywhere in the frozen
  repository, and downstream comparison depends on exact tuple equality, so this first concrete
  extractor deliberately emits none. Signal-based CONFLICTING/COMPATIBLE outcomes therefore stay
  unreachable until a future contract explicitly defines signals; adding any later is a separate
  contract change.

Output order is fixed: all `CLASS` candidates in `parse_result.classes` order, then all
`FUNCTION` candidates in `parse_result.functions` order -- never sorted by line number. Duplicate
candidates (overloads, a repeated `init`, a class and a function sharing a name) are preserved
exactly as parsed: never deduplicated, merged, or re-identified, matching the precedent set by
`StructuralSymbolExtractor`. Downstream, the concrete `foundation.comparer.build_subjects`
rejects two candidates that share a `(relative_path, name)` subject identity; that is a
downstream identity/aggregation concern this per-file, mechanical extractor is not permitted to
solve. See `docs/extractor_foundation_summary.md` for the discovery and lock history behind these
decisions and for the parser-level limitations that pass through unchanged.

This extractor is per-file and mechanical. It performs no quality analysis, ranking, selection,
merging, or cross-file aggregation; those remain the responsibility of later phases.
"""

from src.extractors.foundation.base import (
    FoundationCandidate,
    FoundationCandidateKind,
    FoundationExtractionResult,
    FoundationExtractor,
    require_successful_parse,
)
from src.parsers.base import ParsedClass, ParsedFunction, ParseResult


class StructuralFoundationExtractor(FoundationExtractor):
    """Maps a file's already-parsed classes and free functions onto `FoundationCandidate`
    values.

    Stateless and dependency-free: a single instance handles `ParseResult`s from every one of
    the five existing `Parser` implementations, since each already normalizes its own
    language's constructs into `parsers.base.ParsedClass`/`ParsedFunction`/`ParsedExport`
    before this extractor ever sees them.
    """

    def extract(self, parse_result: ParseResult) -> FoundationExtractionResult:
        """Extract one `FoundationCandidate` per parsed class and per parsed free function.

        Args:
            parse_result: The outcome of parsing one file, as produced by `src.parsers`.

        Returns:
            A successful result carrying the file's `FoundationCandidate` entries: all `CLASS`
            candidates in `parse_result.classes` order, then all `FUNCTION` candidates in
            `parse_result.functions` order, with duplicates included and no sorting applied.
            Empty when the file has no classes and no free functions. Methods are never
            included.

        Raises:
            ValidationError: If `parse_result.succeeded` is False.
        """
        require_successful_parse(parse_result)

        exported_names = frozenset(export.name for export in parse_result.exports)
        class_candidates = tuple(
            _class_to_candidate(parse_result.relative_path, cls, exported_names)
            for cls in parse_result.classes
        )
        function_candidates = tuple(
            _function_to_candidate(parse_result.relative_path, function, exported_names)
            for function in parse_result.functions
        )

        return FoundationExtractionResult.ok(
            relative_path=parse_result.relative_path,
            candidates=class_candidates + function_candidates,
        )


def _class_to_candidate(
    relative_path: str, cls: ParsedClass, exported_names: frozenset[str]
) -> FoundationCandidate:
    """Copy one parsed class's fields onto a `CLASS` `FoundationCandidate`.

    Args:
        relative_path: The file the class was found in.
        cls: The parser's own already-normalized record of the class, taken from
            `parse_result.classes`.
        exported_names: The `.name` of every `ParsedExport` in the file's
            `parse_result.exports`.

    Returns:
        A `FoundationCandidate` of kind `CLASS`. `is_public` is whether `cls.name` is in
        `exported_names`; `has_docstring` is `cls.docstring is not None`; `signals` is always
        empty.
    """
    return FoundationCandidate(
        name=cls.name,
        kind=FoundationCandidateKind.CLASS,
        relative_path=relative_path,
        is_public=cls.name in exported_names,
        has_docstring=cls.docstring is not None,
        signals=(),
        line_number=cls.line_number,
    )


def _function_to_candidate(
    relative_path: str, function: ParsedFunction, exported_names: frozenset[str]
) -> FoundationCandidate:
    """Copy one parsed free function's fields onto a `FUNCTION` `FoundationCandidate`.

    Args:
        relative_path: The file the function was found in.
        function: The parser's own already-normalized record of the function, taken from
            `parse_result.functions` (free functions only -- methods live on their owning
            `ParsedClass` and are never passed here).
        exported_names: The `.name` of every `ParsedExport` in the file's
            `parse_result.exports`.

    Returns:
        A `FoundationCandidate` of kind `FUNCTION`. `is_public` is whether `function.name` is
        in `exported_names`; `has_docstring` is `function.docstring is not None`; `signals` is
        always empty.
    """
    return FoundationCandidate(
        name=function.name,
        kind=FoundationCandidateKind.FUNCTION,
        relative_path=relative_path,
        is_public=function.name in exported_names,
        has_docstring=function.docstring is not None,
        signals=(),
        line_number=function.line_number,
    )
