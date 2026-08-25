"""Tests for `src.application.runner.build_pipeline` and `run_flow`.

Both functions are thin, direct delegations to `src.pipeline.pipeline.Pipeline` (see `runner.py`'s
own module docstring for why); these tests confirm that delegation is faithful -- every behavior
`Pipeline.__init__`/`Pipeline.run` itself guarantees is still observable through
`build_pipeline`/`run_flow` -- rather than re-deriving `Pipeline`'s own test suite. Mirrors
`tests/unit/pipeline/test_pipeline.py`'s own structure and fixtures.
"""

from collections.abc import Sequence

import pytest
from src.application.runner import build_pipeline, run_flow
from src.core.exceptions import ValidationError
from src.core.protocols import SupportsAsyncClose
from src.pipeline.base import Step, StepExecutionError
from src.pipeline.context import PipelineContext
from src.pipeline.pipeline import Pipeline


class _RecordingStep(Step):
    """A `Step` that appends its own name to a shared log and writes a marker into context."""

    def __init__(self, name: str, log: list[str]) -> None:
        self._name = name
        self._log = log

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        self._log.append(self._name)
        context.set(self._name, True)
        return context


class _FailingStep(Step):
    """A `Step` that always raises, to exercise failure propagation through `run_flow`."""

    def __init__(self, name: str, error: Exception) -> None:
        self._name = name
        self._error = error

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        raise self._error


class _FakeResource:
    """A fake `SupportsAsyncClose` resource used to verify cleanup runs through `run_flow`."""

    def __init__(self) -> None:
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


def _steps(names: Sequence[str], log: list[str]) -> list[Step]:
    return [_RecordingStep(name, log) for name in names]


class TestBuildPipeline:
    """Tests for `build_pipeline`'s construction and validation."""

    def test_returns_a_pipeline_instance(self) -> None:
        pipeline = build_pipeline("analyze", [])
        assert isinstance(pipeline, Pipeline)

    def test_exposes_name_steps_and_resources_as_given(self) -> None:
        log: list[str] = []
        steps = _steps(["collect", "parse"], log)
        resource = _FakeResource()
        pipeline = build_pipeline("analyze", steps, resources=[resource])
        assert pipeline.name == "analyze"
        assert pipeline.steps == tuple(steps)
        assert pipeline.resources == (resource,)

    def test_accepts_empty_steps(self) -> None:
        pipeline = build_pipeline("empty", [])
        assert pipeline.steps == ()

    def test_defaults_resources_to_empty(self) -> None:
        pipeline = build_pipeline("analyze", [])
        assert pipeline.resources == ()

    def test_rejects_blank_name(self) -> None:
        with pytest.raises(ValidationError):
            build_pipeline("  ", [])

    def test_rejects_duplicate_step_names(self) -> None:
        log: list[str] = []
        with pytest.raises(ValidationError) as excinfo:
            build_pipeline("analyze", _steps(["collect", "collect"], log))
        assert excinfo.value.details["names"] == ["collect", "collect"]


class TestRunFlow:
    """Tests for `run_flow`'s execution of an already-built `Pipeline`."""

    @pytest.mark.asyncio
    async def test_runs_steps_in_construction_order(self) -> None:
        log: list[str] = []
        pipeline = build_pipeline("analyze", _steps(["collect", "parse", "extract"], log))
        await run_flow(pipeline)
        assert log == ["collect", "parse", "extract"]

    @pytest.mark.asyncio
    async def test_returns_a_typed_pipeline_result(self) -> None:
        log: list[str] = []
        pipeline = build_pipeline("analyze", _steps(["collect", "parse"], log))
        result = await run_flow(pipeline)
        assert result.pipeline_name == "analyze"
        assert result.step_names() == ("collect", "parse")
        assert all(outcome.succeeded for outcome in result.step_outcomes)

    @pytest.mark.asyncio
    async def test_starts_from_a_fresh_context_when_none_given(self) -> None:
        log: list[str] = []
        pipeline = build_pipeline("analyze", _steps(["collect"], log))
        result = await run_flow(pipeline)
        assert result.context.get("collect") is True

    @pytest.mark.asyncio
    async def test_starts_from_the_given_context_when_provided(self) -> None:
        log: list[str] = []
        pipeline = build_pipeline("analyze", _steps(["collect"], log))
        seeded = PipelineContext(values={"seed": "value"})
        result = await run_flow(pipeline, seeded)
        assert result.context.get("seed") == "value"
        assert result.context.get("collect") is True

    @pytest.mark.asyncio
    async def test_empty_pipeline_returns_no_outcomes_and_unchanged_context(self) -> None:
        pipeline = build_pipeline("empty", [])
        seeded = PipelineContext(values={"seed": "value"})
        result = await run_flow(pipeline, seeded)
        assert result.step_outcomes == ()
        assert result.context.get("seed") == "value"


class TestFailurePropagation:
    """Tests for how `run_flow` surfaces a failing `Step`."""

    @pytest.mark.asyncio
    async def test_step_exception_is_wrapped_in_step_execution_error(self) -> None:
        log: list[str] = []
        original = ValueError("boom")
        steps: list[Step] = [_RecordingStep("collect", log), _FailingStep("parse", original)]
        pipeline = build_pipeline("analyze", steps)
        with pytest.raises(StepExecutionError) as excinfo:
            await run_flow(pipeline)
        assert excinfo.value.details["pipeline"] == "analyze"
        assert excinfo.value.details["failed_step"] == "parse"
        assert excinfo.value.details["completed_steps"] == ["collect"]

    @pytest.mark.asyncio
    async def test_original_exception_is_preserved_as_cause(self) -> None:
        original = ValueError("boom")
        pipeline = build_pipeline("analyze", [_FailingStep("parse", original)])
        with pytest.raises(StepExecutionError) as excinfo:
            await run_flow(pipeline)
        assert excinfo.value.__cause__ is original

    @pytest.mark.asyncio
    async def test_no_step_after_the_failing_one_runs(self) -> None:
        log: list[str] = []
        steps: list[Step] = [
            _RecordingStep("collect", log),
            _FailingStep("parse", ValueError("boom")),
            _RecordingStep("extract", log),
        ]
        pipeline = build_pipeline("analyze", steps)
        with pytest.raises(StepExecutionError):
            await run_flow(pipeline)
        assert log == ["collect"]


class TestResourceCleanup:
    """Tests confirming `run_flow` releases resources through `Pipeline`'s own `finally` block."""

    @pytest.mark.asyncio
    async def test_resources_are_closed_after_a_successful_run(self) -> None:
        resource = _FakeResource()
        pipeline = build_pipeline("analyze", [], resources=[resource])
        await run_flow(pipeline)
        assert resource.close_count == 1

    @pytest.mark.asyncio
    async def test_resources_are_closed_after_a_failed_run(self) -> None:
        resource = _FakeResource()
        pipeline = build_pipeline(
            "analyze", [_FailingStep("parse", ValueError("boom"))], resources=[resource]
        )
        with pytest.raises(StepExecutionError):
            await run_flow(pipeline)
        assert resource.close_count == 1

    def test_resource_type_satisfies_supports_async_close(self) -> None:
        assert isinstance(_FakeResource(), SupportsAsyncClose)


class TestReusability:
    """Tests confirming a `Pipeline` built once can be run through `run_flow` more than once --
    the exact capability splitting `build_pipeline` from `run_flow` is meant to preserve."""

    @pytest.mark.asyncio
    async def test_the_same_built_pipeline_can_be_run_twice_independently(self) -> None:
        log: list[str] = []
        pipeline = build_pipeline("analyze", _steps(["collect"], log))

        first = await run_flow(pipeline, PipelineContext(values={"run": "first"}))
        second = await run_flow(pipeline, PipelineContext(values={"run": "second"}))

        assert first.context.get("run") == "first"
        assert second.context.get("run") == "second"
        assert log == ["collect", "collect"]

    @pytest.mark.asyncio
    async def test_two_runs_of_the_same_pipeline_produce_equivalent_results(self) -> None:
        log: list[str] = []
        pipeline = build_pipeline("analyze", _steps(["collect", "parse"], log))

        first = await run_flow(pipeline)
        second = await run_flow(pipeline)

        assert first.step_names() == second.step_names() == ("collect", "parse")
