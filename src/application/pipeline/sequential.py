"""Sequential pipeline orchestrator."""

from typing import Any

from application.interfaces.pipeline import Pipeline, PipelineStage
from core.exceptions.application_exceptions import PipelineExecutionError
from core.logging.logger import get_logger
from core.types.common import InputT, OutputT

_logger = get_logger("application.pipeline")


class SequentialPipeline(Pipeline[InputT, OutputT]):
    """A `Pipeline` that runs its stages one after another, in order.

    Type Parameters:
        InputT: Type of data the pipeline accepts as its initial input.
        OutputT: Type of data the pipeline produces as its final output.
    """

    def __init__(self, stages: list[PipelineStage[Any, Any]]) -> None:
        """Initialize the pipeline with an ordered list of stages.

        Args:
            stages: Stages to execute in order. Each stage's output is fed
                as input to the next stage.
        """
        self._stages = stages

    async def run(self, data: InputT) -> OutputT:
        """Execute every stage of the pipeline in order.

        Args:
            data: Initial input to the first stage.

        Returns:
            The output produced by the final stage.

        Raises:
            PipelineExecutionError: If any stage raises an exception.
        """
        current: Any = data
        for stage in self._stages:
            _logger.debug("Executing pipeline stage '%s'", stage.name)
            try:
                current = await stage.execute(current)
            except Exception as exc:
                raise PipelineExecutionError(stage.name, str(exc)) from exc
        return current  # type: ignore[no-any-return]
