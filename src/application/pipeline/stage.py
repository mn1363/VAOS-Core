"""Abstract base implementation for pipeline stages."""

from abc import ABC

from application.interfaces.pipeline import PipelineStage
from core.types.common import InputT, OutputT


class BasePipelineStage(PipelineStage[InputT, OutputT], ABC):
    """Convenience base class carrying a stage's name as an instance field.

    Type Parameters:
        InputT: Type of data this stage consumes.
        OutputT: Type of data this stage produces.
    """

    def __init__(self, name: str) -> None:
        """Initialize the stage with its display name.

        Args:
            name: Human-readable, unique name identifying this stage.
        """
        self._name = name

    @property
    def name(self) -> str:
        """Human-readable, unique name identifying this stage.

        Returns:
            The stage name provided at construction time.
        """
        return self._name
