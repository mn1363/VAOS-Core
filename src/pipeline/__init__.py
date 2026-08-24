"""Pipeline layer: orchestration primitives for coordinating already-existing VAOS capabilities.

`pipeline` is the outermost of the twelve currently-frozen layers. It does not implement
collection, parsing, extraction, analysis, graph assembly, foundation scoring, or persistence --
those are `src.collectors`, `src.parsers`, `src.extractors`, `src.analyzers`, `src.graph`,
`src.foundation`, and `src.storage`/`src.vector`/`src.memory`'s own concerns, all already built
and frozen. This layer only provides the generic machinery to run an ordered sequence of
already-constructed `Step`s -- each one a thin, dependency-injected adapter around one call into
one of those layers -- against one shared, explicit `PipelineContext`, propagating results and
failures deterministically.

Four modules, each self-contained and imported directly by its full path (matching `core`'s own
`__init__.py` precedent of not re-exporting a combined surface):

- `context.py` -- `PipelineContext`, the explicit, typed, in-memory data carried between steps.
- `base.py` -- the `Step` Port, the `PipelineResult`/`StepOutcome` result DTOs, and this layer's
  own exception hierarchy (`PipelineError`, `StepExecutionError`).
- `pipeline.py` -- `Pipeline`, the orchestrator that runs an ordered, dependency-injected sequence
  of `Step`s against one `PipelineContext`.
- `steps.py` -- `CallableStep` and `MapStep`, two generic, reusable `Step` adapters that lift an
  already-existing, already-bound callable (a `Collector.collect`, a `Parser.parse`, an
  `Extractor.extract`, an `Analyzer.analyze`, a graph `Builder.build`, a `foundation` Port method,
  or any `Repository`/`Storage`/`Vector`/`Memory` Port method) into the uniform `Step` contract,
  without this package ever constructing or importing a concrete implementation of any of them.

This layer deliberately does NOT wire together one specific, hardcoded flow across collectors,
parsers, extractors, analyzers, graph, foundation, and storage/vector/memory -- see `pipeline.py`'s
module docstring for why that scope belongs to a future, not-yet-built `application`/`cli`/
`bootstrap` layer rather than to `pipeline` itself.
"""
