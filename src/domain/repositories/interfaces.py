"""Generic repository Port used by the domain and application layers.

Concrete adapters (SQL, NoSQL, in-memory, etc.) live in the infrastructure
or `repository` package and implement this Protocol; the domain layer
only depends on the abstract contract defined here.
"""

from abc import ABC, abstractmethod
from typing import Generic
from uuid import UUID

from core.types.common import EntityT


class Repository(ABC, Generic[EntityT]):
    """Abstract persistence Port for a single entity type.

    Type Parameters:
        EntityT: The domain entity type this repository persists.
    """

    @abstractmethod
    async def get(self, entity_id: UUID) -> EntityT | None:
        """Retrieve a single entity by identifier.

        Args:
            entity_id: Identifier of the entity to retrieve.

        Returns:
            The matching entity, or None if no entity exists with that id.
        """
        ...

    @abstractmethod
    async def add(self, entity: EntityT) -> None:
        """Persist a new entity.

        Args:
            entity: The entity to add to the underlying store.
        """
        ...

    @abstractmethod
    async def update(self, entity: EntityT) -> None:
        """Persist changes to an existing entity.

        Args:
            entity: The entity, with updated field values, to save.
        """
        ...

    @abstractmethod
    async def delete(self, entity_id: UUID) -> None:
        """Remove an entity from the underlying store.

        Args:
            entity_id: Identifier of the entity to delete.
        """
        ...

    @abstractmethod
    async def list(self) -> list[EntityT]:
        """Retrieve every entity currently in the underlying store.

        Returns:
            A list of every persisted entity of this repository's type.
        """
        ...
