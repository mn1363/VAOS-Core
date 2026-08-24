"""`Pipeline`: runs an ordered, dependency-injected sequence of `Step`s against one shared
`PipelineContext`.

A `Pipeline` coordinates already-existing VAOS capabilities -- it never constructs a `Collector`,
`Parser`, `Extractor`, `Analyzer`, graph `Builder`, `foundation` Port, or `Repository`/`Storage`/
`Vector`/`Memory` Port itself. Every `Step` it runs, and every closeable resource it releases when
a run finishes, is supplied at construction time; see `__init__`'s own docstring, and this
package's own module docstring for the fuller architectural picture.

This module deliberately does not define one specific, hardcoded flow across collectors, parsers,
extractors, analyzers, graph, foundation, and storage/vector/memory (e.g. a single
`build_analysis_pipeline(...)` factory wiring all of them together). Which Ports to run, in what
order, and with what `input_keys`/`output_key` wiring between them, is a set of concrete choices
about one particular analysis flow -- not a fact about orchestration machinery itself, and this
phase's own brief scopes `pipeline` to exactly four files (`base.py`, `context.py`, `pipeline.py`,
`steps.py`), none named for a specific flow. A future, not-yet-built `application`/`cli`/
`bootstrap` layer (already named as a "no lower layer may import pipeline" outer layer in this
phase's own dependency rule) is the natural place to assemble one specific `Pipeline` instance out
of concrete, already-constructed collectors/parsers/etc. and this layer's generic `Step` adapters.
"""

from collections.abc import Sequence

from src.core.logging import get_logger
from src.core.protocols import SupportsAsyncClose

from .base import (
    PipelineResult,
    Step,
    StepExecutionError,
    StepOutcome,
    require_non_blank,
    require_unique_step_names,
)
from .context import PipelineContext

_logger = get_logger("pipeline")


class Pipeline:
    """Coordinates an ordered, fixed sequence of `Step`s against one shared `PipelineContext`.

    Every `Step` a `Pipeline` runs, and every `SupportsAsyncClose` resource it releases when a run
    finishes, is supplied at construction time (dependency injection) -- a `Pipeline` never
    constructs a `Collector`, `Parser`, database client, or any other lower-layer component
    itself, and holds no hidden service locator or global registry through which one could be
    looked up instead.

    A single `Pipeline` instance is reusable: `run` reads only `self._steps`/`self._resources`
    (fixed at construction) and whatever `PipelineContext` it is given, so calling `run` more than
    once, with independent contexts, produces independent, equally deterministic results.
    """

    def __init__(
        self,
        name: str,
        steps: Sequence[Step],
        *,
        resources: Sequence[SupportsAsyncClose] = (),
    ) -> None:
        """Construct a pipeline from an already-assembled, ordered sequence of steps.

        Args:
            name: Stable identity for this pipeline, used in every `StepExecutionError` it
                raises. Must not be blank.
            steps: The steps this pipeline runs, in the exact order given. May be empty -- see
                `run`'s own docstring for empty-pipeline behavior. Every entry must have a unique
                `Step.name`.
            resources: Closeable resources (typically the concrete `Vector`/`Memory`/`Storage`
                Port instances one or more of `steps` was constructed around) to release, via
                `aclose()`, once a `run` call finishes -- successfully or not. Defaults to `()`:
                releasing nothing, appropriate when `steps` was not built around any resource that
                needs explicit closing.

        Raises:
            ValidationError: If `name` is blank, or if two or more entries in `steps` share the
                same `name` -- see `require_unique_step_names`.
        """
        require_non_blank(name, message="Pipeline: name must not be empty")
        require_unique_step_names(steps)
        self._name = name
        self._steps: tuple[Step, ...] = tuple(steps)
        self._resources: tuple[SupportsAsyncClose, ...] = tuple(resources)

    @property
    def name(self) -> str:
        """This pipeline's own stable identity, exactly as constructed."""
        return self._name

    @property
    def steps(self) -> tuple[Step, ...]:
        """The steps this pipeline runs, in execution order, exactly as constructed."""
        return self._steps

    @property
    def resources(self) -> tuple[SupportsAsyncClose, ...]:
        """The closeable resources this pipeline releases after each `run`, exactly as
        constructed."""
        return self._resources

    async def run(self, context: PipelineContext | None = None) -> PipelineResult:
        """Execute every step in order against `context`, propagating context and failures.

        Steps run strictly in construction order -- `self._steps` is a tuple, never reordered or
        drawn from an unordered collection -- so two `run` calls given equivalent starting
        contexts always execute the same steps in the same order and produce equivalent results.
        An empty pipeline (`steps=()`) is not an error: `run` simply returns immediately with a
        `PipelineResult` carrying no step outcomes and `context` unchanged.

        Args:
            context: The context to run against. Defaults to a fresh, empty `PipelineContext`
                when not given.

        Returns:
            A `PipelineResult` recording every step that ran and the final context, once every
            step has completed without raising.

        Raises:
            StepExecutionError: If any step raises. The original exception is preserved as this
                error's `__cause__`; `details` records this pipeline's `name`, the failing step's
                `name`, and the names of every step that completed successfully first. No step
                after the failing one runs.
        """
        working_context = context if context is not None else PipelineContext()
        outcomes: list[StepOutcome] = []
        try:
            for step in self._steps:
                _logger.debug("pipeline '%s' starting step '%s'", self._name, step.name)
                try:
                    working_context = await step.execute(working_context)
                except Exception as exc:
                    _logger.debug(
                        "pipeline '%s' failed at step '%s': %s", self._name, step.name, exc
                    )
                    raise StepExecutionError(
                        f"pipeline '{self._name}' failed at step '{step.name}': {exc}",
                        details={
                            "pipeline": self._name,
                            "failed_step": step.name,
                            "completed_steps": [outcome.step_name for outcome in outcomes],
                        },
                    ) from exc
                outcomes.append(StepOutcome.ok(step.name))
                _logger.debug("pipeline '%s' completed step '%s'", self._name, step.name)
            return PipelineResult(
                pipeline_name=self._name,
                step_outcomes=tuple(outcomes),
                context=working_context,
            )
        finally:
            for resource in self._resources:
                await resource.aclose()
