"""Abstract scaffolding shared by concrete repository adapters."""

from abc import ABC
from uuid import UUID, uuid4

from core.types.common import EntityT
from domain.repositories.interfaces import Repository


class AbstractRepository(Repository[EntityT], ABC):
    """Base class for concrete repository adapters.

    Provides identifier generation shared by every adapter while leaving
    all persistence operations abstract for subclasses to implement.

    Type Parameters:
        EntityT: The domain entity type this repository persists.
    """

    @staticmethod
    def new_id() -> UUID:
        """Generate a new, unique entity identifier.

        Returns:
            A freshly generated UUID.
        """
        return uuid4()
