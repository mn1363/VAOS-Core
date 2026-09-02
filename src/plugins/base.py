"""Plugin Port: the Phase 18 contract a caller-supplied extension implements.

`Plugin` is a named, `plugins`-layer subtype of the already-frozen `pipeline.base.Step` -- it
adds no new abstract members. A `Plugin` therefore inherits `Step`'s own contract exactly: a
stable `name` property and an `async execute(context: PipelineContext) -> PipelineContext`
method. This mirrors `domain.interfaces.SourceRepositoryStore`'s own relationship to the more
generic `Repository[EntityT]` it subclasses -- a named, layer-specific vocabulary for an already-
generic Port, not a new capability. See `steps.py` in `src.pipeline` for `CallableStep`/`MapStep`,
which a concrete `Plugin` may still delegate to internally if convenient, exactly as any other
concrete `Step` implementation may.

Any `Plugin` instance already satisfies `pipeline.base.Step` by inheritance, so it is already a
valid member of `bootstrap.wiring.build_application`'s existing `extra_steps: Sequence[Step]`
parameter -- no adapter, registry, or wiring change is required to use one; see
`tests.unit.plugins.test_base` for an end-to-end proof of exactly this. This module defines only
the vocabulary; it does not decide how a `Plugin` is discovered, constructed, versioned, or
invoked at runtime -- see this package's own `__init__.py` for the historical `PluginRegistry`/
`Container`-based scaffold this deliberately does not revive, and for why those concerns stay
out of scope here.
"""

from abc import ABC

from src.pipeline.base import Step


class Plugin(Step, ABC):
    """A VAOS plugin: a `pipeline.base.Step` implementation supplied by an outer caller.

    Adds no new abstract members beyond what `Step` already declares (`name`, `execute`) -- a
    concrete plugin implements those two exactly as any other concrete `Step` subclass would.
    Defined as its own named subtype, rather than a bare type alias for `Step`, purely so this
    layer has an explicit identity to document, `isinstance`-check, and extend in a future phase
    without touching `src.pipeline` itself.
    """
