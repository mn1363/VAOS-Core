"""Application layer: the composition point that turns already-built machinery into a runnable
flow.

`application` is the outermost of the thirteen currently-frozen layers. It does not collect,
parse, extract, analyze, build graphs, make Foundation decisions, persist anything, embed or
search vectors, store project knowledge, provide git access, or define orchestration primitives
of its own -- those are `src.collectors`, `src.parsers`, `src.extractors`, `src.analyzers`,
`src.graph`, `src.foundation`, `src.storage`, `src.vector`, `src.memory`, `src.repository`, and
`src.pipeline`'s own concerns, all already built and frozen. `src.pipeline` itself already
provides every orchestration primitive a flow needs (`Pipeline`, `Step`, `CallableStep`,
`MapStep`) but, by its own explicit design, never assembles one specific flow out of them --
`pipeline.pipeline`'s own module docstring names this exact gap as belonging to "a future,
not-yet-built `application`/`cli`/`bootstrap` layer." This package is that layer, for the
`application` name specifically.

One module, `runner.py`, holding this layer's entire public surface: `build_pipeline` and
`run_flow`, two plain functions (no service classes, no use-case classes, no CQRS/command-query
hierarchy) that construct and execute a `Pipeline` from already-constructed `Step`s and
`SupportsAsyncClose` resources supplied by the caller. Neither function constructs a `Collector`,
`Parser`, `Extractor`, `Analyzer`, graph `Builder`, `foundation` Port, or any
`Repository`/`Storage`/`Vector`/`Memory` Port itself, and neither reaches for a service locator or
any global or module-level state -- every dependency arrives as a function argument. See
`runner.py`'s own module docstring for the fuller picture, including why this layer's contract is
deliberately this thin rather than one hardcoded, specific end-to-end analysis flow.
"""
