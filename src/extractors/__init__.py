"""Extractors layer: transforms a single file's already-parsed structure into reusable,
higher-level semantic information.

`extractors` answers "what does this file's parsed structure *mean*, in a form later phases can
reuse directly" -- package/module placement, structural counts, normalized dependency edges, a
focused class/function/constant table, interface-shaped declarations, recognizable code
patterns, and raw foundation-candidacy signals. It does not parse source code itself (that is
`parsers`, already built), analyze quality, score repositories, build graphs, or select
foundations -- those are later, not-yet-built phases' concerns.

Each of its seven subpackages -- `architecture`, `ast`, `foundation`, `imports`, `interfaces`,
`patterns`, `symbols` -- defines exactly one extraction contract in its own `base.py`: an
abstract `...Extractor` Port with a single `extract(parse_result: ParseResult) -> ...Result`
method, an outcome DTO following the same `ok`/`failed` pattern as `parsers.base.ParseResult` and
`collectors.base.CollectionResult`, and the extracted-construct DTOs specific to that concern.
Every contract takes a `parsers.base.ParseResult` as its only input and performs no I/O of its
own, matching `Parser.parse`'s own pure, in-memory, synchronous shape.

Each module here is self-contained and imported directly by its full path (e.g. `from
src.extractors.symbols.base import SymbolExtractor`); this package intentionally does not
re-export a combined surface from `__init__.py`.
"""
