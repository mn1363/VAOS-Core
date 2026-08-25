"""`build_pipeline` and `run_flow`: the two plain functions that make up this layer's entire
public contract.

Both functions do nothing `src.pipeline` does not already do -- `build_pipeline` is a thin,
one-line call to `Pipeline.__init__`, and `run_flow` is a thin, one-line call to `Pipeline.run` --
and that is deliberate, not an oversight. `src.pipeline.pipeline`'s own module docstring is
explicit that assembling a *specific* flow (which `Step`s, in what order, wired to which concrete,
already-constructed `Collector`/`Parser`/`Extractor`/`Analyzer`/graph `Builder`/`foundation`
Port/`Repository`/`Storage`/`Vector`/`Memory` Port) is "a set of concrete choices about one
particular analysis flow -- not a fact about orchestration machinery itself," and that no frozen
phase through Phase 13 defines what that one particular flow should be. Hardcoding one here would
mean inventing an unevidenced business flow, directly contradicting this phase's own "do not
create speculative abstractions" instruction. `tests/unit/pipeline/test_integration.py` already
demonstrates the established, frozen precedent for *how* a caller builds the `Step`s a flow needs
-- constructing `CallableStep`/`MapStep` directly around already-constructed Port instances, no
further abstraction in between. This module does not reimplement that: it receives the result
(already-built `Step`s, already-constructed resources) as plain function arguments and supplies
only the two actions no other frozen layer performs yet -- constructing a `Pipeline` from them,
and executing one.

Splitting "construct" from "execute" into two separate functions, rather than one function that
does both, preserves a capability `Pipeline` itself is explicitly designed for and that a single
combined function would silently discard: `pipeline.pipeline.Pipeline`'s own class docstring notes
that "a single `Pipeline` instance is reusable... calling `run` more than once, with independent
contexts, produces independent, equally deterministic results." A caller that wants that -- run
the same assembled flow against several `PipelineContext`s -- can call `build_pipeline` once and
`run_flow` several times; a single one-shot function could not offer that without its own added
surface.

Neither function raises anything of its own. `build_pipeline` propagates whatever
`Pipeline.__init__` raises (`ValidationError`, for a blank `name` or duplicate `Step` names) and
`run_flow` propagates whatever `Pipeline.run` raises (`StepExecutionError`, for a `Step` that
failed) unchanged -- matching `core.exceptions`'s own stated rule that a layer defines its own
exception subclass only for a failure mode genuinely new to that layer, not for argument checks
already owned by whatever it wraps. This layer introduces no new failure mode of its own, so it
defines no new exception type; see `docs/phase14_summary.md` for the fuller reasoning.
"""

from collections.abc import Sequence

from src.core.logging import get_logger
from src.core.protocols import SupportsAsyncClose
from src.pipeline.base import PipelineResult, Step
from src.pipeline.context import PipelineContext
from src.pipeline.pipeline import Pipeline

_logger = get_logger("application")


def build_pipeline(
    name: str,
    steps: Sequence[Step],
    *,
    resources: Sequence[SupportsAsyncClose] = (),
) -> Pipeline:
    """Assemble an already-constructed sequence of `Step`s and resources into a `Pipeline`.

    Every dependency this function needs -- `steps`, `resources` -- arrives as a plain function
    argument (constructor/function dependency injection); this function never constructs a
    `Collector`, `Parser`, `Extractor`, `Analyzer`, graph `Builder`, `foundation` Port,
    `Repository`/`Storage`/`Vector`/`Memory` Port, or a `Step` wrapping any of them, and never
    looks one up through a service locator or global registry. Building the `Step`s a particular
    flow needs -- typically via `src.pipeline.steps.CallableStep`/`MapStep` around already-
    constructed, concrete lower-layer Port instances, exactly as `tests/unit/pipeline/
    test_integration.py` already demonstrates -- is the caller's responsibility; this function's
    own part of "build the required Pipeline Steps" is assembling that already-built sequence,
    together with `resources`, into one `Pipeline`.

    Args:
        name: Stable identity for the resulting pipeline. Passed through to `Pipeline.__init__`
            unchanged; must not be blank.
        steps: The already-constructed steps the resulting pipeline runs, in the exact order
            given. May be empty. Every entry must have a unique `Step.name`.
        resources: Already-constructed `SupportsAsyncClose` resources (typically the concrete
            `Vector`/`Memory`/`Storage` Port instances one or more of `steps` was built around)
            for the resulting pipeline to release after each `run`. Defaults to `()`.

    Returns:
        A `Pipeline` constructed from `name`, `steps`, and `resources`, not yet run.

    Raises:
        ValidationError: If `name` is blank, or if two or more entries in `steps` share the same
            `name` -- raised by `Pipeline.__init__` itself; see its own docstring.
    """
    _logger.debug("building pipeline '%s' from %d step(s)", name, len(steps))
    return Pipeline(name, steps, resources=resources)


async def run_flow(
    pipeline: Pipeline,
    context: PipelineContext | None = None,
) -> PipelineResult:
    """Execute an already-constructed `Pipeline` and return its typed result.

    `pipeline` arrives as a plain function argument (constructor/function dependency injection);
    this function never constructs a `Pipeline` itself -- see `build_pipeline` -- and never
    reaches for one through a service locator or global registry.

    Args:
        pipeline: The already-constructed pipeline to run, typically returned by `build_pipeline`.
        context: The context to run `pipeline` against. Defaults to a fresh, empty
            `PipelineContext` when not given -- passed straight through to `Pipeline.run`.

    Returns:
        The `PipelineResult` `pipeline.run(context)` returns, once every step has completed
        without raising.

    Raises:
        StepExecutionError: If any step in `pipeline` raises while running -- raised by
            `Pipeline.run` itself; see its own docstring. No step after the failing one runs, and
            `pipeline`'s own resources are still released before this propagates.
    """
    _logger.debug("running pipeline '%s'", pipeline.name)
    return await pipeline.run(context)
