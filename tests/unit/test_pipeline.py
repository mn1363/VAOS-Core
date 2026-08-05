"""Unit tests for the sequential pipeline orchestrator."""

import pytest

from application.pipeline.sequential import SequentialPipeline
from application.pipeline.stage import BasePipelineStage
from core.exceptions.application_exceptions import PipelineExecutionError


class _AddOneStage(BasePipelineStage[int, int]):
    """A trivial stage that increments its input by one."""

    def __init__(self) -> None:
        """Initialize the stage with a fixed name."""
        super().__init__(name="add_one")

    async def execute(self, data: int) -> int:
        """Return `data` incremented by one."""
        return data + 1


class _FailingStage(BasePipelineStage[int, int]):
    """A trivial stage that always raises an exception."""

    def __init__(self) -> None:
        """Initialize the stage with a fixed name."""
        super().__init__(name="failing")

    async def execute(self, data: int) -> int:
        """Always raise a `ValueError`."""
        raise ValueError("boom")


@pytest.mark.asyncio
async def test_pipeline_runs_stages_in_order() -> None:
    """Stages should execute in order, each receiving the prior output."""
    pipeline: SequentialPipeline[int, int] = SequentialPipeline(
        stages=[_AddOneStage(), _AddOneStage()]
    )
    result = await pipeline.run(0)
    assert result == 2


@pytest.mark.asyncio
async def test_pipeline_wraps_stage_errors() -> None:
    """A failing stage should surface as a `PipelineExecutionError`."""
    pipeline: SequentialPipeline[int, int] = SequentialPipeline(stages=[_FailingStage()])
    with pytest.raises(PipelineExecutionError):
        await pipeline.run(0)
