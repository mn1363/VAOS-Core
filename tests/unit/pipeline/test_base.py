"""Tests for `src.pipeline.base`: the `Step` contract, result DTOs, and exception hierarchy."""

import pytest
from src.core.exceptions import ValidationError, VAOSError
from src.pipeline.base import (
    PipelineError,
    PipelineResult,
    Step,
    StepExecutionError,
    StepOutcome,
    require_non_blank,
    require_unique_step_names,
)
from src.pipeline.context import PipelineContext


class _NamedStep(Step):
    """Minimal concrete `Step` used only to exercise the `Step` contract itself."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: PipelineContext) -> PipelineContext:
        return context


def test_step_cannot_be_instantiated_directly() -> None:
    """`Step` is an ABC: it must not be constructible without a `name`/`execute` override."""
    with pytest.raises(TypeError):
        Step()  # type: ignore[abstract]


def test_step_subclass_with_both_members_is_constructible() -> None:
    """A subclass providing both `name` and `execute` satisfies the contract."""
    step = _NamedStep("greet")
    assert step.name == "greet"


class TestStepOutcome:
    """Tests for `StepOutcome`."""

    def test_ok_builds_successful_outcome(self) -> None:
        outcome = StepOutcome.ok("collect")
        assert outcome.step_name == "collect"
        assert outcome.succeeded is True
        assert outcome.error_message is None

    def test_failed_builds_failed_outcome(self) -> None:
        outcome = StepOutcome.failed("collect", "boom")
        assert outcome.succeeded is False
        assert outcome.error_message == "boom"

    def test_rejects_blank_step_name(self) -> None:
        with pytest.raises(ValidationError):
            StepOutcome(step_name="  ", succeeded=True)

    def test_rejects_successful_outcome_with_error_message(self) -> None:
        with pytest.raises(ValidationError):
            StepOutcome(step_name="collect", succeeded=True, error_message="unexpected")

    def test_rejects_failed_outcome_without_error_message(self) -> None:
        with pytest.raises(ValidationError):
            StepOutcome(step_name="collect", succeeded=False)


class TestPipelineResult:
    """Tests for `PipelineResult`."""

    def test_holds_pipeline_name_outcomes_and_context(self) -> None:
        context = PipelineContext()
        outcomes = (StepOutcome.ok("collect"), StepOutcome.ok("parse"))
        result = PipelineResult(
            pipeline_name="analyze", step_outcomes=outcomes, context=context
        )
        assert result.pipeline_name == "analyze"
        assert result.step_outcomes == outcomes
        assert result.context is context

    def test_step_count_matches_number_of_outcomes(self) -> None:
        result = PipelineResult(
            pipeline_name="analyze",
            step_outcomes=(StepOutcome.ok("collect"), StepOutcome.ok("parse")),
            context=PipelineContext(),
        )
        assert result.step_count == 2

    def test_step_names_preserves_order(self) -> None:
        result = PipelineResult(
            pipeline_name="analyze",
            step_outcomes=(StepOutcome.ok("collect"), StepOutcome.ok("parse")),
            context=PipelineContext(),
        )
        assert result.step_names() == ("collect", "parse")

    def test_empty_step_outcomes_is_valid(self) -> None:
        result = PipelineResult(
            pipeline_name="empty", step_outcomes=(), context=PipelineContext()
        )
        assert result.step_count == 0

    def test_rejects_blank_pipeline_name(self) -> None:
        with pytest.raises(ValidationError):
            PipelineResult(pipeline_name="  ", step_outcomes=(), context=PipelineContext())

    def test_rejects_a_failed_step_outcome(self) -> None:
        """A `PipelineResult` is only ever built after a fully successful run; a failed entry
        would be internally inconsistent, so it is rejected rather than silently accepted."""
        with pytest.raises(ValidationError):
            PipelineResult(
                pipeline_name="analyze",
                step_outcomes=(StepOutcome.failed("collect", "boom"),),
                context=PipelineContext(),
            )


class TestExceptionHierarchy:
    """Tests for `PipelineError`/`StepExecutionError`'s place in the shared VAOS hierarchy."""

    def test_pipeline_error_is_a_vaos_error(self) -> None:
        assert issubclass(PipelineError, VAOSError)

    def test_step_execution_error_is_a_pipeline_error(self) -> None:
        assert issubclass(StepExecutionError, PipelineError)

    def test_step_execution_error_preserves_cause_and_details(self) -> None:
        original = ValueError("boom")
        try:
            try:
                raise original
            except ValueError as exc:
                raise StepExecutionError(
                    "pipeline 'analyze' failed at step 'parse': boom",
                    details={
                        "pipeline": "analyze",
                        "failed_step": "parse",
                        "completed_steps": ["collect"],
                    },
                ) from exc
        except StepExecutionError as wrapped:
            assert wrapped.__cause__ is original
            assert wrapped.details["pipeline"] == "analyze"
            assert wrapped.details["failed_step"] == "parse"
            assert wrapped.details["completed_steps"] == ["collect"]


class TestRequireHelpers:
    """Tests for the `require_non_blank`/`require_unique_step_names` validation helpers."""

    def test_require_non_blank_returns_value_when_valid(self) -> None:
        assert require_non_blank("analyze", message="unused") == "analyze"

    def test_require_non_blank_raises_with_given_message(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            require_non_blank("  ", message="Pipeline: name must not be empty")
        assert str(excinfo.value) == "Pipeline: name must not be empty"

    def test_require_unique_step_names_returns_steps_when_unique(self) -> None:
        steps = [_NamedStep("collect"), _NamedStep("parse")]
        assert require_unique_step_names(steps) is steps

    def test_require_unique_step_names_raises_on_duplicate(self) -> None:
        steps = [_NamedStep("collect"), _NamedStep("collect")]
        with pytest.raises(ValidationError) as excinfo:
            require_unique_step_names(steps)
        assert excinfo.value.details["names"] == ["collect", "collect"]
