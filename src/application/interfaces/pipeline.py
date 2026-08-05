"""Pipeline and pipeline-stage Ports used to orchestrate processing."""

from abc import ABC, abstractmethod
from typing import Generic

from core.types.common import InputT, OutputT


class PipelineStage(ABC, Generic[InputT, OutputT]):
    """A single, named step within a `Pipeline`.

    Type Parameters:
        InputT: Type of data this stage consumes.
        OutputT: Type of data this stage produces.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable, unique name identifying this stage.

        Returns:
            The stage name.
        """
        ...

    @abstractmethod
    async def execute(self, data: InputT) -> OutputT:
        """Process `data` and return the stage's output.

        Args:
            data: Input produced by the previous stage (or initial input).

        Returns:
            The output to pass on to the next stage.
        """
        ...


class Pipeline(ABC, Generic[InputT, OutputT]):
    """An ordered composition of `PipelineStage` instances.

    Type Parameters:
        InputT: Type of data the pipeline accepts as its initial input.
        OutputT: Type of data the pipeline produces as its final output.
    """

    @abstractmethod
    async def run(self, data: InputT) -> OutputT:
        """Execute every stage of the pipeline in order.

        Args:
            data: Initial input to the first stage.

        Returns:
            The output produced by the final stage.
        """
        ...
