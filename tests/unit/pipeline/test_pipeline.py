"""Tests for `src.pipeline.pipeline.Pipeline`."""

from collections.abc import Sequence

import pytest
from src.core.exceptions import ValidationError
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
    """A `Step` that always raises, to exercise `Pipeline.run`'s failure handling."""

    def __init__(self, name: str, error: Exception) -> None:
        self._name = name
        self._error = error

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        raise self._error


class _FakeResource:
    """A fake `SupportsAsyncClose` resource used to verify lifecycle behavior."""

    def __init__(self) -> None:
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


def _steps(names: Sequence[str], log: list[str]) -> list[Step]:
    return [_RecordingStep(name, log) for name in names]


class TestConstruction:
    """Tests for `Pipeline.__init__` validation."""

    def test_rejects_blank_name(self) -> None:
        with pytest.raises(ValidationError):
            Pipeline("  ", [])

    def test_rejects_duplicate_step_names(self) -> None:
        log: list[str] = []
        with pytest.raises(ValidationError) as excinfo:
            Pipeline("analyze", _steps(["collect", "collect"], log))
        assert excinfo.value.details["names"] == ["collect", "collect"]

    def test_accepts_empty_steps(self) -> None:
        pipeline = Pipeline("empty", [])
        assert pipeline.steps == ()

    def test_exposes_name_steps_and_resources_as_constructed(self) -> None:
        log: list[str] = []
        steps = _steps(["collect", "parse"], log)
        resource = _FakeResource()
        pipeline = Pipeline("analyze", steps, resources=[resource])
        assert pipeline.name == "analyze"
        assert pipeline.steps == tuple(steps)
        assert pipeline.resources == (resource,)


class TestOrderedExecution:
    """Tests for in-order execution and context propagation."""

    @pytest.mark.asyncio
    async def test_runs_steps_in_construction_order(self) -> None:
        log: list[str] = []
        pipeline = Pipeline("analyze", _steps(["collect", "parse", "extract"], log))
        await pipeline.run()
        assert log == ["collect", "parse", "extract"]

    @pytest.mark.asyncio
    async def test_context_written_by_earlier_step_is_visible_to_later_steps(self) -> None:
        log: list[str] = []

        class _ReadsPriorOutput(Step):
            @property
            def name(self) -> str:
                return "parse"

            async def execute(self, context: PipelineContext) -> PipelineContext:
                assert context.require("collect") is True
                log.append("parse-saw-collect")
                return context

        pipeline = Pipeline(
            "analyze", [_RecordingStep("collect", log), _ReadsPriorOutput()]
        )
        await pipeline.run()
        assert log == ["collect", "parse-saw-collect"]

    @pytest.mark.asyncio
    async def test_starts_from_a_fresh_context_when_none_given(self) -> None:
        log: list[str] = []
        pipeline = Pipeline("analyze", _steps(["collect"], log))
        result = await pipeline.run()
        assert result.context.get("collect") is True

    @pytest.mark.asyncio
    async def test_starts_from_the_given_context_when_provided(self) -> None:
        log: list[str] = []
        pipeline = Pipeline("analyze", _steps(["collect"], log))
        seeded = PipelineContext(values={"seed": "value"})
        result = await pipeline.run(seeded)
        assert result.context.get("seed") == "value"
        assert result.context.get("collect") is True


class TestResultCollection:
    """Tests for the `PipelineResult` returned by a successful `run`."""

    @pytest.mark.asyncio
    async def test_returns_one_outcome_per_step_in_order(self) -> None:
        log: list[str] = []
        pipeline = Pipeline("analyze", _steps(["collect", "parse"], log))
        result = await pipeline.run()
        assert result.pipeline_name == "analyze"
        assert result.step_names() == ("collect", "parse")
        assert all(outcome.succeeded for outcome in result.step_outcomes)

    @pytest.mark.asyncio
    async def test_empty_pipeline_returns_no_outcomes_and_unchanged_context(self) -> None:
        pipeline = Pipeline("empty", [])
        seeded = PipelineContext(values={"seed": "value"})
        result = await pipeline.run(seeded)
        assert result.step_outcomes == ()
        assert result.context.get("seed") == "value"


class TestFailurePropagation:
    """Tests for `Pipeline.run`'s failure handling."""

    @pytest.mark.asyncio
    async def test_step_exception_is_wrapped_in_step_execution_error(self) -> None:
        log: list[str] = []
        original = ValueError("boom")
        steps: list[Step] = [
            _RecordingStep("collect", log),
            _FailingStep("parse", original),
        ]
        pipeline = Pipeline("analyze", steps)
        with pytest.raises(StepExecutionError) as excinfo:
            await pipeline.run()
        assert excinfo.value.details["pipeline"] == "analyze"
        assert excinfo.value.details["failed_step"] == "parse"
        assert excinfo.value.details["completed_steps"] == ["collect"]

    @pytest.mark.asyncio
    async def test_original_exception_is_preserved_as_cause(self) -> None:
        original = ValueError("boom")
        pipeline = Pipeline("analyze", [_FailingStep("parse", original)])
        with pytest.raises(StepExecutionError) as excinfo:
            await pipeline.run()
        assert excinfo.value.__cause__ is original

    @pytest.mark.asyncio
    async def test_no_step_after_the_failing_one_runs(self) -> None:
        log: list[str] = []
        steps: list[Step] = [
            _RecordingStep("collect", log),
            _FailingStep("parse", ValueError("boom")),
            _RecordingStep("extract", log),
        ]
        pipeline = Pipeline("analyze", steps)
        with pytest.raises(StepExecutionError):
            await pipeline.run()
        assert log == ["collect"]

    @pytest.mark.asyncio
    async def test_failure_on_the_first_step_reports_no_completed_steps(self) -> None:
        pipeline = Pipeline("analyze", [_FailingStep("collect", ValueError("boom"))])
        with pytest.raises(StepExecutionError) as excinfo:
            await pipeline.run()
        assert excinfo.value.details["completed_steps"] == []


class TestDeterministicExecution:
    """Tests that repeated runs behave identically."""

    @pytest.mark.asyncio
    async def test_running_twice_produces_the_same_step_order(self) -> None:
        log: list[str] = []
        pipeline = Pipeline("analyze", _steps(["collect", "parse", "extract"], log))
        await pipeline.run()
        await pipeline.run()
        assert log == [
            "collect",
            "parse",
            "extract",
            "collect",
            "parse",
            "extract",
        ]

    @pytest.mark.asyncio
    async def test_running_twice_produces_equivalent_results(self) -> None:
        log: list[str] = []
        pipeline = Pipeline("analyze", _steps(["collect", "parse"], log))
        first = await pipeline.run()
        second = await pipeline.run()
        assert first.step_names() == second.step_names()
        assert first.pipeline_name == second.pipeline_name


class TestDependencyInjection:
    """Tests confirming `Pipeline` never constructs its own steps or resources."""

    @pytest.mark.asyncio
    async def test_pipeline_only_ever_calls_the_injected_steps(self) -> None:
        log: list[str] = []
        step = _RecordingStep("collect", log)
        pipeline = Pipeline("analyze", [step])
        await pipeline.run()
        assert log == ["collect"]

    @pytest.mark.asyncio
    async def test_resources_are_the_exact_injected_instances(self) -> None:
        resource = _FakeResource()
        pipeline = Pipeline("analyze", [], resources=[resource])
        await pipeline.run()
        assert pipeline.resources == (resource,)


class TestLifecycle:
    """Tests for resource closing after a `run` call."""

    @pytest.mark.asyncio
    async def test_resources_are_closed_after_a_successful_run(self) -> None:
        log: list[str] = []
        resource = _FakeResource()
        pipeline = Pipeline("analyze", _steps(["collect"], log), resources=[resource])
        await pipeline.run()
        assert resource.close_count == 1

    @pytest.mark.asyncio
    async def test_resources_are_closed_even_when_a_step_fails(self) -> None:
        resource = _FakeResource()
        pipeline = Pipeline(
            "analyze", [_FailingStep("collect", ValueError("boom"))], resources=[resource]
        )
        with pytest.raises(StepExecutionError):
            await pipeline.run()
        assert resource.close_count == 1

    @pytest.mark.asyncio
    async def test_no_resources_is_a_valid_default(self) -> None:
        log: list[str] = []
        pipeline = Pipeline("analyze", _steps(["collect"], log))
        result = await pipeline.run()
        assert result.step_names() == ("collect",)


class TestReusability:
    """Tests confirming one `Pipeline` instance can be run more than once."""

    @pytest.mark.asyncio
    async def test_same_instance_can_run_successfully_more_than_once(self) -> None:
        log: list[str] = []
        pipeline = Pipeline("analyze", _steps(["collect"], log))
        first = await pipeline.run(PipelineContext())
        second = await pipeline.run(PipelineContext())
        assert first.context is not second.context
        assert first.step_names() == second.step_names() == ("collect",)

    @pytest.mark.asyncio
    async def test_steps_and_resources_are_unchanged_between_runs(self) -> None:
        log: list[str] = []
        steps = _steps(["collect"], log)
        pipeline = Pipeline("analyze", steps)
        await pipeline.run()
        assert pipeline.steps == tuple(steps)
