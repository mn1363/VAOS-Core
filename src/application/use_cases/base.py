"""Base use case providing shared scaffolding for concrete use cases."""

from abc import ABC

from application.interfaces.use_case import UseCase
from core.logging.logger import get_logger
from core.types.common import InputT, OutputT


class BaseUseCase(UseCase[InputT, OutputT], ABC):
    """Common base class for use cases, providing a namespaced logger.

    Type Parameters:
        InputT: Type of the use case's input DTO.
        OutputT: Type of the use case's output DTO.
    """

    def __init__(self) -> None:
        """Initialize the use case with a logger namespaced to its class."""
        self._logger = get_logger(f"use_case.{type(self).__name__}")
