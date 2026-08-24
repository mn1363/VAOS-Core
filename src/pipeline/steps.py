"""Reusable `Step` adapters that lift an already-existing callable into the `Step` contract.

Two adapters cover every orchestration shape the frozen architecture's Ports actually present, so
most `Pipeline` construction never requires a bespoke `Step` subclass:

`CallableStep` wraps a single call whose arguments are each read from one `PipelineContext` key
and whose single return value is written back under one more -- the shape of `Collector.collect`,
`Parser.parse`, any `Extractor.extract`/`Analyzer.analyze` call, a graph `Builder.build` call, any
`foundation` Port call, and every `Repository`/`Storage`/`Vector`/`Memory` Port method.

`MapStep` applies a single-item callable across every element of a sequence read from one
`PipelineContext` key, in that sequence's own order, collecting the per-item outputs into a tuple
written back under one more -- the shape needed to run a per-file Port (a `Parser`, `Extractor`,
`Analyzer`) across every file `Collector.collect` found, before handing the collected results to a
repository-wide graph `Builder` or `foundation` Port.

Both adapters accept a synchronous or an asynchronous callable (`is_async`); which one to pass is
decided entirely by the caller supplying `func` -- this module makes no assumption about which of
the layers it might adapt are sync (`parsers`, `extractors`, `analyzers`, `graph`, `foundation`)
and which are async (`collectors`, `storage`, `vector`, `memory`), and never constructs or imports
a concrete implementation of any of them itself; see the `pipeline` package's own module docstring
and `Step`'s own docstring in `base.py`.

Neither adapter runs its items concurrently: `MapStep` iterates its input sequence strictly in
order, one call at a time, matching this phase's own "do not implement speculative ... async
infrastructure unless the existing repository already requires it" instruction and its separate
determinism requirement -- concurrent execution would risk nondeterministic completion order for
no benefit `Pipeline` itself can rely on, since ordering, not throughput, is what this layer's
brief asks for.
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from .base import Step, require_non_blank
from .context import PipelineContext

_Callable = Callable[..., Any] | Callable[..., Awaitable[Any]]


class CallableStep(Step):
    """Adapts a single already-existing callable into a `Step`.

    `CallableStep` never constructs the Port it wraps: `func` is supplied already bound (e.g. a
    `collector_instance.collect` bound method, or a `functools.partial` over a free function), so
    this class never violates this phase's "Pipeline must accept its steps/components through
    explicit construction ... no hidden service locator" rule.
    """

    def __init__(
        self,
        name: str,
        func: _Callable,
        *,
        input_keys: Sequence[str] = (),
        output_key: str,
        is_async: bool = False,
    ) -> None:
        """Construct a step that calls `func` with arguments read from `input_keys`.

        Args:
            name: Stable identity for this step. Must not be blank.
            func: The already-bound callable this step delegates to. Called positionally, in
                `input_keys` order, as `func(*args)`.
            input_keys: `PipelineContext` keys to `require` and pass to `func`, in order. Defaults
                to `()`: calling `func` with no arguments.
            output_key: `PipelineContext` key `func`'s return value is written back under. Must
                not be blank.
            is_async: Whether `func` is a coroutine function that must be awaited. Defaults to
                False.

        Raises:
            ValidationError: If `name` or `output_key` is blank.
        """
        self._name = require_non_blank(name, message="CallableStep: name must not be empty")
        self._func = func
        self._input_keys = tuple(input_keys)
        self._output_key = require_non_blank(
            output_key, message="CallableStep: output_key must not be empty"
        )
        self._is_async = is_async

    @property
    def name(self) -> str:
        """This step's own stable identity, exactly as constructed."""
        return self._name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Call `func` with arguments read from `input_keys`, and write its result back.

        Args:
            context: The shared context to read `input_keys` from and write `output_key` into.

        Returns:
            `context`, with `func`'s return value stored under `output_key`.

        Raises:
            NotFoundError: If any of `input_keys` is not present in `context`.
            Whatever `func` itself raises.
        """
        args = [context.require(key) for key in self._input_keys]
        if self._is_async:
            result = await self._func(*args)
        else:
            result = self._func(*args)
        context.set(self._output_key, result)
        return context


class MapStep(Step):
    """Applies a single-item callable across every element of a sequence, preserving order.

    Like `CallableStep`, `MapStep` never constructs the Port it wraps: `func` is supplied already
    bound, and is called once per item, strictly in the input sequence's own order.
    """

    def __init__(
        self,
        name: str,
        func: _Callable,
        *,
        input_key: str,
        output_key: str,
        is_async: bool = False,
    ) -> None:
        """Construct a step that maps `func` over the sequence stored under `input_key`.

        Args:
            name: Stable identity for this step. Must not be blank.
            func: The already-bound, single-item callable this step applies to each element of
                the sequence read from `input_key`, as `func(item)`.
            input_key: `PipelineContext` key holding the sequence to map over. Must not be blank.
            output_key: `PipelineContext` key the tuple of per-item results is written back
                under. Must not be blank.
            is_async: Whether `func` is a coroutine function that must be awaited. Defaults to
                False.

        Raises:
            ValidationError: If `name`, `input_key`, or `output_key` is blank.
        """
        self._name = require_non_blank(name, message="MapStep: name must not be empty")
        self._func = func
        self._input_key = require_non_blank(
            input_key, message="MapStep: input_key must not be empty"
        )
        self._output_key = require_non_blank(
            output_key, message="MapStep: output_key must not be empty"
        )
        self._is_async = is_async

    @property
    def name(self) -> str:
        """This step's own stable identity, exactly as constructed."""
        return self._name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Apply `func` to every element read from `input_key`, in order, and write the results.

        Args:
            context: The shared context to read `input_key` from and write `output_key` into.

        Returns:
            `context`, with a tuple of `func`'s per-item return values, in input order, stored
            under `output_key`.

        Raises:
            NotFoundError: If `input_key` is not present in `context`.
            Whatever `func` itself raises, on the first item for which it raises -- no later item
                is processed.
        """
        items = context.require(self._input_key)
        outputs: list[Any] = []
        for item in items:
            result = await self._func(item) if self._is_async else self._func(item)
            outputs.append(result)
        context.set(self._output_key, tuple(outputs))
        return context
