"""Use case Port: the entrypoint contract for application logic."""

from abc import ABC, abstractmethod
from typing import Generic

from core.types.common import InputT, OutputT


class UseCase(ABC, Generic[InputT, OutputT]):
    """A single, self-contained application operation.

    Type Parameters:
        InputT: Type of the use case's input DTO.
        OutputT: Type of the use case's output DTO.
    """

    @abstractmethod
    async def execute(self, input_data: InputT) -> OutputT:
        """Execute the use case.

        Args:
            input_data: The input required to perform this operation.

        Returns:
            The result of performing this operation.
        """
        ...
