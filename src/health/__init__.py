"""Health layer: the Phase 20 contract for orchestrating a service's health check.

`health` answers a question `core.protocols.SupportsHealthCheck` has left open since Phase 1:
something that checks every registered service and reports whether all of them are healthy --
with exactly one thing, `Health`, a small class holding a fixed, constructor-injected
`Sequence[SupportsHealthCheck]`. `runtime` (Phase 19) explicitly declined to be that something:
its own module docstring states that it "does not reference `core.protocols.SupportsHealthCheck`,
which, unlike `SupportsLifecycle`, carries no 'future `X` package' attribution anywhere in the
frozen codebase" -- leaving `SupportsHealthCheck` with zero concrete implementers and zero
orchestrator anywhere in the frozen codebase through Phase 19. This package is that orchestrator,
and nothing more: it constructs no concrete `SupportsHealthCheck` service itself, exactly as
`runtime.runtime.Runtime` coordinates already-existing `SupportsLifecycle` services without ever
constructing one, and exactly as `pipeline.pipeline.Pipeline` coordinates already-existing
`Step`s without ever constructing a `Collector`/`Parser`/etc.

Unlike `Runtime.start`/`stop`, `Health.health_check` is not a single, ordered, all-or-nothing
action -- it is a scan of independent services that may legitimately encounter many independent
failures, the same distinction `pipeline.base`'s own module docstring draws between
`Pipeline.run`/`Runtime.start`/`Runtime.stop`'s fail-fast shape and
`collectors.base.CollectionResult`/`parsers.base.ParseResult`/every
extractor-analyzer-graph-foundation Port's own "convert a failure into a value, don't raise"
shape. Every registered service is checked, in registration order, regardless of any earlier
result: a service that returns `False`, or whose own `health_check()` raises, is treated as
unhealthy and neither stops the scan nor escapes `Health.health_check()` itself. No new
exception type is defined by this package -- under this contract, `Health.health_check()` never
raises. `SupportsHealthCheck` has no identity/name field (unlike `pipeline.base.Step.name`), so
no per-service identity is introduced merely to build a richer report; the result is a single
aggregate `bool`, the same shape `SupportsHealthCheck.health_check` itself already returns for
one service, extended to many.

This package does not construct, discover, or configure any concrete `SupportsHealthCheck`
service. It does not import `runtime`, `bootstrap`, `pipeline`, `cli`, or `api`: the accepted
Phase 20 responsibility -- orchestrating an already constructor-injected sequence -- is fully
satisfiable importing `core` alone, and the family resemblance to `runtime` (both orchestrate a
`Sequence` of a `core.protocols` shape) is not, by itself, evidence of a dependency between them
-- the same standard `runtime.__init__` already applied to reject `bootstrap`/`pipeline` as
dependencies despite documentary pairing. It introduces no `Container`, no registry, no service
locator, no DI framework, no dynamic discovery, no configuration schema, and no
`cli`/`api`/`bootstrap` integration of any kind -- none of that is part of the locked Phase 20
contract. No `errors.py` exists in this package: under this contract, `Health.health_check()`
never raises, so there is no failure mode of this layer's own to define an exception for.

`health.py` is this package's entire public surface. This package intentionally does not
re-export a combined surface beyond that from `__init__.py`.
"""
