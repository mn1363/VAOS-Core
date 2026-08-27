"""Bootstrap layer: the outer wiring layer that constructs concrete Ports and hands them to
`application`.

`bootstrap` is one of three layers `pipeline.pipeline`'s own module docstring names as sharing
the same unclaimed responsibility -- "a future, not-yet-built `application`/`cli`/`bootstrap`
layer" -- assembling one specific `Pipeline` instance "out of concrete, already-constructed
collectors/parsers/etc.". `application` (Phase 14) already claimed the narrower half of that gap:
turning already-built `Step`s into a runnable `Pipeline` (`build_pipeline`) and running it
(`run_flow`), while explicitly declining to construct a single concrete `Collector`, `Parser`,
`Extractor`, `Analyzer`, graph `Builder`, `foundation` Port, or any
`Repository`/`Storage`/`Vector`/`Memory` Port itself. This package is that layer, for the
`bootstrap` name specifically: it reads `core.config.AppConfig`, selects and constructs the
concrete lower-layer Port implementations a configured analysis flow needs, wraps them into
`Step`s via `pipeline.steps.CallableStep`/`MapStep`, and calls `application.build_pipeline`/
`application.run_flow` -- never `Pipeline.run` directly.

One module, `wiring.py`, holding this layer's entire public surface: `build_repository_client`,
`build_workspace_manager`, `build_storage`, `build_vector_store`, `build_collector` (each
constructing one concrete Port from `AppConfig`), and `build_application`/`bootstrap` (the two
top-level functions that compose the rest into one flow and, for `bootstrap`, also run it). All
are plain functions -- no service classes, no use-case classes, no CQRS hierarchy, no DI
container, no service locator, no global registry -- matching this phase's own explicit
instruction and the "constructor/function dependency injection" convention every earlier phase
already established (see `pipeline.pipeline`'s and `application.runner`'s own module docstrings).
Every dependency `wiring.py` itself needs arrives as a function argument; nothing is read from
module-level or global state.

`bootstrap` does not implement `core.protocols.SupportsLifecycle` and does not introduce a
`start`/`stop` pair of its own. That Protocol, and the "reverse order, on shutdown" lifecycle it
describes, is explicitly reserved for "the future `bootstrap` **and** `runtime` packages" (see
`core.protocols.SupportsLifecycle`'s own docstring) -- but nothing in the frozen codebase through
Phase 14 implements it, and the only lifecycle behavior that actually exists and is exercised
anywhere is `pipeline.pipeline.Pipeline.run`'s own `finally`-block release of every
`SupportsAsyncClose` resource it was given, once, at the end of each run. This phase supplies
`SupportsAsyncClose`-shaped resources into that already-existing mechanism (see
`build_storage`/`build_vector_store`) rather than inventing a second, parallel lifecycle
mechanism of its own; a persistent, cross-run service lifecycle -- if one is ever needed -- is a
`runtime` package's concern, not this one's.

`bootstrap` may import every already-frozen layer through `application` (`core`, `domain`,
`repository`, `collectors`, `parsers`, `extractors`, `analyzers`, `graph`, `foundation`,
`storage`, `vector`, `memory`, `pipeline`, `application`) but not `api`, `cli`, or `plugins` --
none of which exist yet, and none of which any evidence connects to `bootstrap` as a dependency
in either direction. No Phase 1-14 layer may import `src.bootstrap` back.

`bootstrap` does not fabricate a concrete `memory.base.MemoryStore` implementation: no concrete
`MemoryStore` exists anywhere in the frozen codebase (only the abstract Port, in
`src.memory.base`), so `build_application`/`bootstrap` accept an already-constructed
`MemoryStore | None` from the caller instead of constructing one themselves -- the same
"implement the Port defined here rather than reaching for a concrete store" relationship
`storage` (Phase 10) already established towards `vector` (Phase 11) before Phase 11 existed.
"""
