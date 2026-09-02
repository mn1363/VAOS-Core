"""Plugins layer: the Phase 18 contract for a caller-supplied `pipeline.base.Step` extension.

`plugins` answers "what must an outer caller build to add its own unit of work to a VAOS flow,
without any frozen layer knowing about it in advance" -- exactly one thing: a `Plugin`, this
package's own named subtype of the already-frozen `pipeline.base.Step`, adding zero new abstract
members. It does not extend `collectors`, `parsers`, `extractors`, `analyzers`, `graph`, or
`foundation` -- each of those is a closed, fixed-cardinality set (a hardcoded number of concrete
implementations, selected by a hardcoded branch in `bootstrap.wiring`, keyed to a frozen
`domain.entities` enum) with no extension mechanism of its own. `Step`, together with
`bootstrap.wiring.build_application`'s already-existing `extra_steps: Sequence[Step]` parameter,
is the one genuinely generic, caller-extensible attachment point the frozen architecture already
provides -- see `docs/phase18_summary.md` for the full survey this conclusion is drawn from.

This package does not decide how a `Plugin` is discovered, registered, versioned, given a
lifecycle, or wired into `bootstrap`, `cli`, or `api` at runtime; those are later, not-yet-decided
concerns, exactly as `parsers`/`extractors`/`analyzers`/`graph`/`foundation` remain fully built but
unwired into any live flow as of Phase 17. Any `Plugin` instance already satisfies `Step` by
inheritance, so a caller who constructs one directly can already pass it to `extra_steps` today --
no adapter, registry, or change to `src.bootstrap`/`src.pipeline` is required.

A `src/plugins/` package existed once before, at Phase 2-3: built around a `core.container.
container.Container`-based `Plugin(ABC)` (`name`, `version`, `async setup(container)`, `async
teardown()`) and a name-keyed `PluginRegistry`. It was removed in the "Restore VAOS after stale
module cleanup" commit that preceded Phase 4, and is structurally incompatible with the plain-
function, no-DI-container, no-service-locator convention every layer since has followed. None of
that -- no `Container`, no `PluginRegistry`, no `setup`/`teardown` lifecycle, no dynamic discovery
of any kind -- exists in this package.

`base.py` is this package's entire public surface: the `Plugin` class. This package intentionally
does not re-export a combined surface beyond that from `__init__.py`.
"""
