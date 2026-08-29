"""CLI layer: the command-line process entry point for the existing VAOS default analysis flow.

`cli` is the outermost of the sixteen currently-frozen layers. It does not collect, parse,
extract, analyze, build graphs, make Foundation decisions, persist anything, embed or search
vectors, store project knowledge, provide git access, define orchestration primitives, or wire
concrete Ports together -- those are `src.collectors`, `src.parsers`, `src.extractors`,
`src.analyzers`, `src.graph`, `src.foundation`, `src.storage`, `src.vector`, `src.memory`,
`src.repository`, `src.pipeline`, `src.application`, and `src.bootstrap`'s own concerns, all
already built and frozen. `bootstrap` already exposes a single, complete, callable flow --
`bootstrap.bootstrap(config) -> PipelineResult` -- that reads `core.config.AppConfig`, constructs
every concrete Port the configured default flow needs, and runs it. This package's entire job is
translating a process invocation (`argv`, a process exit code, stdout/stderr) into and out of that
one existing call: parse `--config`/`--help`/`--version`, load configuration via
`core.config.load_config`, call `bootstrap.bootstrap`, render its `PipelineResult` or a raised
`core.exceptions.VAOSError` to the terminal, and return the matching exit code.

One module, `main.py`, holding this layer's entire public surface: `main(argv=None) -> int`, the
synchronous process entry point (an `asyncio.run` bridge over `bootstrap.bootstrap`'s own async
signature), plus `build_parser()` and a private async execution helper. All are plain functions --
no service classes, no CLI controller class, no CQRS hierarchy, no DI container, no service
locator, no global registry -- matching the "constructor/function dependency injection" convention
every earlier phase already established (see `pipeline.pipeline`'s, `application.runner`'s, and
`bootstrap.wiring`'s own module docstrings).

`cli` introduces no CLI framework beyond the standard library's own `argparse`; no new dependency
was added, and `pyproject.toml` was not touched. `cli` does not construct a `Collector`, `Parser`,
`Extractor`, `Analyzer`, graph `Builder`, `foundation` Port, or any
`Repository`/`Storage`/`Vector`/`Memory` Port itself -- every one of those stays `bootstrap`'s own
concern, invoked only through `bootstrap.bootstrap`. `cli` does not introduce `plugins` or `api`,
and does not revive the deleted, superseded, pre-Phase-3 `Container`/`PluginRegistry`-based CLI
scaffold that once existed under this same package name.

`cli` may import every already-frozen layer through `bootstrap` (`core`, `domain`, `repository`,
`collectors`, `parsers`, `extractors`, `analyzers`, `graph`, `foundation`, `storage`, `vector`,
`memory`, `pipeline`, `application`, `bootstrap`) but not `api` or `plugins` -- neither of which
exists yet, and neither of which any evidence connects to `cli` as a dependency in either
direction. No Phase 1-15 layer may import `src.cli` back.
"""
