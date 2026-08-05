"""Unit of Work Port for coordinating transactional boundaries."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self


class UnitOfWork(ABC):
    """Coordinates a set of repository operations as a single transaction."""

    @abstractmethod
    async def __aenter__(self) -> Self:
        """Begin the unit of work.

        Returns:
            This unit of work, ready for use as an async context manager.
        """
        ...

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """End the unit of work, rolling back if an exception occurred.

        Args:
            exc_type: Type of the exception raised in the `with` block, if any.
            exc_value: The exception instance raised, if any.
            traceback: The exception's traceback, if any.
        """
        ...

    @abstractmethod
    async def commit(self) -> None:
        """Persist every change made during this unit of work."""
        ...

    @abstractmethod
    async def rollback(self) -> None:
        """Discard every change made during this unit of work."""
        ...
