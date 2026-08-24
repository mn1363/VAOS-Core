"""Pipeline-layer Port, result DTOs, and this layer's own exception hierarchy.

`Step` is the contract every unit of work a `Pipeline` runs must satisfy: a stable `name` and an
`execute(context)` method that reads whatever it needs from a `PipelineContext`, does its own
work -- almost always by delegating entirely to an already-existing, constructor-injected Port
from a lower layer (see `steps.py`) -- and returns the context with its own output written back
in. A `Step` never catches an exception the work it delegates to raises; see `Pipeline.run`'s own
docstring in `pipeline.py` for where that responsibility lives instead.

`StepOutcome` and `PipelineResult` follow the same succeeded/`ok()`/`failed()` result-DTO shape
`src.collectors.base.CollectionResult`, `src.parsers.base.ParseResult`, and every extractor/
analyzer/graph/foundation Port already establish -- with one deliberate difference, explained in
`PipelineResult`'s own docstring: a `Pipeline` run is a single, ordered, all-or-nothing execution,
not a per-item scan that may legitimately encounter many independent failures, so a `Pipeline` run
that fails is reported by raising `StepExecutionError`, not by returning a `PipelineResult` with
`succeeded=False`. `StepOutcome` still keeps its own `failed()` constructor: it is used internally,
by `Pipeline.run`, to record the one step that failed as structured detail on the
`StepExecutionError` it raises (see `pipeline.py`), even though a `PipelineResult` -- only ever
constructed after a fully successful run -- never itself contains a failed `StepOutcome`.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from src.core.exceptions import ValidationError, VAOSError

from .context import PipelineContext


class PipelineError(VAOSError):
    """Base class for every exception explicitly raised by `src.pipeline` itself.

    Distinct from an exception raised by a lower-layer Port a `Step` delegates to (a
    `ValidationError`, a `GitCommandError`, a `StorageError`, ...): that original exception is
    never replaced -- it propagates as this error's `__cause__` -- so no type information or
    detail from the original failure is lost. See `StepExecutionError`.
    """


class StepExecutionError(PipelineError):
    """Raised by `Pipeline.run` when a `Step` raises while it is executing.

    Attributes:
        message: Human-readable description of what went wrong.
        details: Structured context about the failure: which pipeline (`"pipeline"`) and which
            step (`"failed_step"`) failed, and the names of every step that completed
            successfully beforehand (`"completed_steps"`), in execution order. The original
            exception itself is preserved as this error's `__cause__` via `raise ... from exc`,
            not re-described here, so it can still be inspected, matched on its own type, or
            re-raised by a caller that catches `StepExecutionError`.
    """


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """Outcome of a single `Step.execute` call within one `Pipeline.run` call.

    Attributes:
        step_name: `Step.name` of the step this outcome describes.
        succeeded: Whether the step completed without raising.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    step_name: str
    succeeded: bool
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `step_name`, `succeeded`, and `error_message` are consistent.

        Raises:
            ValidationError: If `step_name` is blank, if a successful outcome carries an error
                message, or if a failed outcome carries no error message.
        """
        if not self.step_name.strip():
            raise ValidationError("StepOutcome: step_name must not be empty")
        if self.succeeded and self.error_message is not None:
            raise ValidationError(
                "StepOutcome: error_message must be None when succeeded is True"
            )
        if not self.succeeded and self.error_message is None:
            raise ValidationError(
                "StepOutcome: error_message is required when succeeded is False"
            )

    @classmethod
    def ok(cls, step_name: str) -> "StepOutcome":
        """Build a successful outcome.

        Args:
            step_name: `Step.name` of the step that completed successfully.

        Returns:
            A `StepOutcome` with `succeeded=True`.
        """
        return cls(step_name=step_name, succeeded=True)

    @classmethod
    def failed(cls, step_name: str, error_message: str) -> "StepOutcome":
        """Build a failed outcome.

        Args:
            step_name: `Step.name` of the step that raised.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `StepOutcome` with `succeeded=False`.
        """
        return cls(step_name=step_name, succeeded=False, error_message=error_message)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Outcome of one complete, successful `Pipeline.run` call.

    Only ever constructed after every step in the pipeline has completed without raising -- see
    this module's own docstring for why a failed run is instead reported by `Pipeline.run` raising
    `StepExecutionError`, rather than by a `PipelineResult` with a `succeeded` field set to False.

    Attributes:
        pipeline_name: `Pipeline.name` of the pipeline that produced this result.
        step_outcomes: One successful `StepOutcome` per step that ran, in execution order.
        context: The final `PipelineContext`, after every step's own output has been written into
            it.
    """

    pipeline_name: str
    step_outcomes: tuple[StepOutcome, ...]
    context: PipelineContext

    def __post_init__(self) -> None:
        """Validate that `pipeline_name` is non-blank and every `step_outcomes` entry succeeded.

        Raises:
            ValidationError: If `pipeline_name` is blank, or if any entry in `step_outcomes` did
                not succeed -- a `PipelineResult` is only ever constructed after a fully
                successful run, so a failed entry here would be internally inconsistent.
        """
        if not self.pipeline_name.strip():
            raise ValidationError("PipelineResult: pipeline_name must not be empty")
        if any(not outcome.succeeded for outcome in self.step_outcomes):
            raise ValidationError(
                "PipelineResult: every step_outcomes entry must have succeeded"
            )

    @property
    def step_count(self) -> int:
        """Total number of steps that ran to produce this result."""
        return len(self.step_outcomes)

    def step_names(self) -> tuple[str, ...]:
        """The name of every step that ran, in execution order.

        Returns:
            A tuple of `StepOutcome.step_name`, in the same order as `step_outcomes`.
        """
        return tuple(outcome.step_name for outcome in self.step_outcomes)


class Step(ABC):
    """A single, named unit of work a `Pipeline` executes, in order, against a shared context.

    A concrete `Step` decides how to translate one or more `PipelineContext` values into a call
    into an already-existing, constructor-injected lower-layer Port, and where to write that
    call's own output back into the context; it does not itself collect, parse, extract, analyze,
    build a graph, score, or persist anything -- seethe `pipeline` package's own module docstring.
    See `steps.py` for `CallableStep` and `MapStep`, the two generic adapters that satisfy this
    contract for any already-existing callable, so most `Pipeline` construction never requires a
    bespoke `Step` subclass at all.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identity of this step within its owning `Pipeline`.

        Used, unchanged, as `StepOutcome.step_name` and in `StepExecutionError.details` if this
        step raises -- so it must be unique among the steps of any one `Pipeline` (see
        `Pipeline.__init__`).
        """
        ...

    @abstractmethod
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute this step's own work against `context`.

        Args:
            context: The shared context, carrying whatever earlier steps in the same `Pipeline`
                run have already written to it.

        Returns:
            `context`, after this step has read whatever inputs it needs and written its own
            output back into it (typically the same object, mutated in place, since
            `PipelineContext` itself is a plain mutable container -- see `context.py`).

        Raises:
            Whatever the underlying call this step delegates to raises. A `Step` implementation
            must not catch and swallow that exception -- `Pipeline.run` is what wraps a raised
            exception with this step's identity and its owning pipeline's identity; a `Step` that
            swallowed it here would make that wrapping, and the failure itself, invisible.
        """
        ...


def require_non_blank(value: str, *, message: str) -> str:
    """Validate that `value` is not blank.

    Shared by `Pipeline.__init__` and by `steps.py`'s adapters for their own `name`/`output_key`/
    `input_key` constructor arguments, so every "must not be blank" check in this package raises
    the same `ValidationError` shape.

    Args:
        value: The value to validate.
        message: The exact message to raise if `value` is blank (e.g. `"Pipeline: name must not
            be empty"`).

    Returns:
        `value`, unchanged.

    Raises:
        ValidationError: If `value` is blank.
    """
    if not value.strip():
        raise ValidationError(message)
    return value


def require_unique_step_names(steps: Sequence[Step]) -> Sequence[Step]:
    """Validate that no two steps in `steps` share a `name`.

    Every `Pipeline.__init__` call validates its own `steps` argument this way first, so a caller
    error (two steps with the same `name`, which would make `StepOutcome`/`StepExecutionError`
    step identities ambiguous) is reported the same way -- as an immediate `ValidationError` --
    matching every `require_*` helper already established across `src.extractors`/`src.analyzers`/
    `src.graph`/`src.foundation`.

    Args:
        steps: The raw `steps` argument passed to `Pipeline.__init__`.

    Returns:
        `steps`, unchanged.

    Raises:
        ValidationError: If two or more entries in `steps` share the same `name`.
    """
    names = [step.name for step in steps]
    if len(set(names)) != len(names):
        raise ValidationError(
            "Pipeline: steps must have unique names", details={"names": names}
        )
    return steps
