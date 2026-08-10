"""Analyzers layer: turns a single file's already-extracted semantic information into
analytical results -- measurements, normalized metrics, and evaluated indicators.

`analyzers` answers "what does this file's extracted information *tell us*, in a form later
phases can reuse directly" -- structural placement facts, complexity-proxy ratios, dependency
exposure, documentation coverage, normalized density metrics, and evaluated quality/security/test
indicators. It does not parse source code, collect repositories, extract raw structures, modify
repositories, generate graphs, select foundations, or perform ranking -- those are `parsers`,
`collectors`, `extractors` (already built) or `graph`, `foundation`, `pipeline` (later, not-yet-
built phases') concerns.

Each of its eight subpackages -- `architecture`, `complexity`, `dependency`, `documentation`,
`metrics`, `quality`, `security`, `tests` -- defines exactly one analysis contract in its own
`base.py`: an abstract `...Analyzer` Port with a single `analyze(extraction_result: ...) -> ...
AnalysisResult` method, an outcome DTO following the same `ok`/`failed` pattern as
`extractors.architecture.base.ArchitectureExtractionResult` and its six siblings, and the
analysis-result DTOs specific to that concern. Every contract takes exactly one of `src.
extractors`'s per-file extraction-result DTOs as its only input and performs no I/O of its own,
matching each `...Extractor.extract`'s own pure, in-memory, synchronous, per-file shape --
assembling many files' results into a repository-wide view stays a later, not-yet-built phase's
job (`graph`, `pipeline`), not this layer's.

Each module here is self-contained and imported directly by its full path (e.g. `from
src.analyzers.quality.base import QualityAnalyzer`); this package intentionally does not
re-export a combined surface from `__init__.py`.
"""
