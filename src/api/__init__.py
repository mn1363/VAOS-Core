"""API layer: the HTTP transport boundary for VAOS.

`api` is the seventeenth layer -- the first built on top of the sixteen already-frozen Phase 1-16
layers -- and Phase 17's own package.
Like `cli` (Phase 16), it introduces no business logic of its own -- it only translates an
external invocation into and out of already-built machinery, this time an HTTP request/response
instead of a process invocation. See `docs/phase17_api_contract.md`-equivalent discovery reports
for the full evidence trail this phase was built from.

**Phase 17's confirmed initial scope is exactly one operation: `GET /health`.** A liveness probe
answers a question about this process alone -- "is it up and able to answer requests" -- and
needs no call into any inner layer to do so. Unlike `cli.main`, which bridges every invocation
into `bootstrap.bootstrap` (`src.bootstrap.wiring.bootstrap`), `GET /health` calls nothing in
`src.bootstrap`, `src.application`, `src.pipeline`, `src.storage`, `src.vector`, `src.memory`, or
any other already-frozen layer -- running the full default collect/persist flow as a side effect
of a liveness check would itself be business logic this layer must not contain, and would give a
health probe unwanted, expensive side effects on every call. The confirmed instruction that "API
must use... the existing `bootstrap.bootstrap()` flow" is the standing rule for any *future*
operation that performs real analysis work, exactly as `cli` already does -- not a requirement
that this initial, pure liveness endpoint invoke it. `src.api` therefore imports nothing from any
other `src.*` package for this phase; see `tests/unit/api/test_dependency_boundaries.py` for the
enforced boundary.

One module, `main.py`, holding this layer's entire public surface: `health`, the route handler,
and `create_app`, the factory function that assembles the ASGI application -- both plain functions
(no service classes, no dependency-injection container, no route-controller hierarchy), matching
`application.build_pipeline`/`run_flow`, `bootstrap`'s `build_*`/`bootstrap`, and `cli`'s
`build_parser`/`main`'s own identical "constructor-style function, no framework beyond what the
task needs" convention.

**Explicitly not revived.** A `src/api/` package existed once before, at Phase 2-3
(`git show 031c67c:src/api/`), built around a FastAPI app wired through a `core.Container`
dependency-injection container, an `infrastructure.composition.register_infrastructure` call, and
a `plugins.registry.PluginRegistry` -- none of which exist in the current architecture. That
scaffold was deleted in the "Restore VAOS after stale module cleanup" commit and is not restored,
reused, or referenced here; this package's `FastAPI` app is constructed directly, with no
container, no plugin registry, and no `infrastructure` package. `src.cli.__init__`'s own
disclaimer for the deleted `Container`/`PluginRegistry`-based CLI scaffold applies here in the
same spirit, for the deleted API scaffold specifically.

This package does not import, and is not imported by, `src.cli` -- the two are independent
composition roots over the same inner layers, exactly the relationship the deleted, superseded
architecture document showed for these two names (historical shape only; nothing about that
document's own technology choices for `plugins`/`infrastructure` carries any current authority).
"""
