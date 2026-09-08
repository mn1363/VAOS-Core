"""Runtime layer: the Phase 19 contract for orchestrating a service's start/stop lifecycle.

`runtime` answers the question `core.protocols.SupportsLifecycle`'s own docstring has left open
since Phase 1 -- something that starts every registered service on startup and stops them, in
reverse order, on shutdown -- with exactly one thing: `Runtime`, a small class holding a fixed,
constructor-injected `Sequence[SupportsLifecycle]`. `bootstrap` explicitly declined to be that
something (see its own `__init__.py`, Design Decision #2: "a persistent, cross-run service
lifecycle -- if one is ever needed -- is a `runtime` package's concern, not this one's"), leaving
`SupportsLifecycle` with zero concrete implementers and zero orchestrator anywhere in the frozen
codebase through Phase 18. This package is that orchestrator, and nothing more: it constructs no
concrete `SupportsLifecycle` service itself, exactly as `pipeline.pipeline.Pipeline` coordinates
already-existing `Step`s without ever constructing a `Collector`/`Parser`/etc., and exactly as
`plugins.base.Plugin` adds vocabulary to an already-existing Port rather than a new capability.

`runtime` was named as a still-open, not-yet-built package by `core.protocols.SupportsLifecycle`
(Phase 1), `storage.__init__` (Phase 10), and `bootstrap.__init__` (Phase 15) -- the sole
remaining member of the six historically-named-but-unbuilt candidates Phase 14's own contract
discovery first surfaced (`application`, `bootstrap`, `runtime`, `plugins`, `api`, `cli`), the
other five of which have each already been implemented, in sequence, as exactly the phase their
name predicted. Unlike `plugins`, `runtime` was never part of the deleted Phase 2-3 scaffold --
`git ls-tree -r 031c67c` (the last commit before that scaffold was removed) contains no
`src/runtime` at any point in this repository's history. Building it revives nothing.

This package does not construct, discover, or configure any concrete `SupportsLifecycle`
service. It does not import `bootstrap` or `pipeline`: the accepted Phase 19 responsibility --
orchestrating an already constructor-injected sequence -- is fully satisfiable importing `core`
alone, and the two package names appearing together in documentation is not, by itself, evidence
of a dependency (see `docs/phase19_summary.md` for the full contract-discovery survey this
conclusion is drawn from). It does not reference `core.protocols.SupportsHealthCheck`, which,
unlike `SupportsLifecycle`, carries no "future `X` package" attribution anywhere in the frozen
codebase and is therefore out of scope. It introduces no `Container`, no `PluginRegistry`-style
registry, no service locator, no DI framework, no dynamic discovery, no configuration schema, and
no `cli`/`api` integration of any kind -- none of that is part of the locked Phase 19 contract.

`errors.py` and `runtime.py` are this package's entire public surface. This package intentionally
does not re-export a combined surface beyond that from `__init__.py`.
"""
