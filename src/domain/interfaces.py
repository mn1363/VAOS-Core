"""Domain interfaces: the persistence Ports outer layers implement.

`domain` does not implement persistence itself -- it only defines the
contract. The future `repository` package (Phase 3) is expected to provide
concrete adapters implementing these Ports.
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar
from uuid import UUID

from .entities import AnalysisRun, Finding, SourceFile, SourceRepository

#: Generic type variable representing the entity type a `Repository` Port
#: persists.
EntityT = TypeVar("EntityT")


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


class SourceRepositoryStore(Repository[SourceRepository], ABC):
    """Persistence Port for `SourceRepository` entities.

    Named `...Store` rather than `...Repository` to avoid a confusing
    stutter: the entity type itself is already named `SourceRepository`
    (it contains the word "repository" as part of its own domain name),
    and `Repository` is also the name of the generic persistence-pattern
    base class above.
    """

    @abstractmethod
    async def get_by_source_uri(self, source_uri: str) -> SourceRepository | None:
        """Retrieve a repository by the location it was collected from.

        Args:
            source_uri: Location to look up.

        Returns:
            The matching repository, or None if none has that source URI.
        """
        ...


class SourceFileRepository(Repository[SourceFile], ABC):
    """Persistence Port for `SourceFile` entities."""

    @abstractmethod
    async def list_by_repository(self, repository_id: UUID) -> list[SourceFile]:
        """Retrieve every file belonging to a given repository.

        Args:
            repository_id: Identifier of the owning repository.

        Returns:
            Every `SourceFile` whose `repository_id` matches.
        """
        ...


class AnalysisRunRepository(Repository[AnalysisRun], ABC):
    """Persistence Port for `AnalysisRun` entities."""

    @abstractmethod
    async def list_by_repository(self, repository_id: UUID) -> list[AnalysisRun]:
        """Retrieve every analysis run for a given repository.

        Args:
            repository_id: Identifier of the analyzed repository.

        Returns:
            Every `AnalysisRun` whose `repository_id` matches.
        """
        ...


class FindingRepository(Repository[Finding], ABC):
    """Persistence Port for `Finding` entities."""

    @abstractmethod
    async def list_by_analysis_run(self, analysis_run_id: UUID) -> list[Finding]:
        """Retrieve every finding produced by a given analysis run.

        Args:
            analysis_run_id: Identifier of the owning analysis run.

        Returns:
            Every `Finding` whose `analysis_run_id` matches.
        """
        ...
