"""Unit tests for `src.domain.interfaces`."""

from uuid import UUID, uuid4

import pytest
from src.domain.entities import (
    AnalysisRun,
    Finding,
    RepositoryProvider,
    SourceFile,
    SourceRepository,
)
from src.domain.interfaces import (
    AnalysisRunRepository,
    FindingRepository,
    Repository,
    SourceFileRepository,
    SourceRepositoryStore,
)


def test_repository_cannot_be_instantiated_directly() -> None:
    """The generic `Repository` Port is abstract and must not be instantiable."""
    with pytest.raises(TypeError):
        Repository()  # type: ignore[abstract]


def test_source_repository_store_cannot_be_instantiated_directly() -> None:
    """`SourceRepositoryStore` is abstract and must not be instantiable."""
    with pytest.raises(TypeError):
        SourceRepositoryStore()  # type: ignore[abstract]


def test_source_file_repository_cannot_be_instantiated_directly() -> None:
    """`SourceFileRepository` is abstract and must not be instantiable."""
    with pytest.raises(TypeError):
        SourceFileRepository()  # type: ignore[abstract]


def test_analysis_run_repository_cannot_be_instantiated_directly() -> None:
    """`AnalysisRunRepository` is abstract and must not be instantiable."""
    with pytest.raises(TypeError):
        AnalysisRunRepository()  # type: ignore[abstract]


def test_finding_repository_cannot_be_instantiated_directly() -> None:
    """`FindingRepository` is abstract and must not be instantiable."""
    with pytest.raises(TypeError):
        FindingRepository()  # type: ignore[abstract]


class _InMemorySourceRepositoryStore(SourceRepositoryStore):
    """A minimal, fully-working in-memory implementation.

    Used only to prove that `SourceRepositoryStore`'s contract is coherent
    and genuinely implementable -- not a production adapter.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._items: dict[UUID, SourceRepository] = {}

    async def get(self, entity_id: UUID) -> SourceRepository | None:
        """Retrieve a repository by id, or None if not present."""
        return self._items.get(entity_id)

    async def add(self, entity: SourceRepository) -> None:
        """Store a new repository."""
        self._items[entity.id] = entity

    async def update(self, entity: SourceRepository) -> None:
        """Overwrite the stored repository with the same id."""
        self._items[entity.id] = entity

    async def delete(self, entity_id: UUID) -> None:
        """Remove a repository by id, if present."""
        self._items.pop(entity_id, None)

    async def list(self) -> list[SourceRepository]:
        """Return every stored repository."""
        return list(self._items.values())

    async def get_by_source_uri(self, source_uri: str) -> SourceRepository | None:
        """Return the stored repository with a matching source URI, if any."""
        return next((r for r in self._items.values() if r.source_uri == source_uri), None)


@pytest.mark.asyncio
async def test_in_memory_source_repository_store_round_trip() -> None:
    """A concrete `SourceRepositoryStore` should support the full CRUD + lookup contract."""
    store = _InMemorySourceRepositoryStore()
    repo = SourceRepository(
        name="vaos", source_uri="https://github.com/x/vaos", provider=RepositoryProvider.GITHUB
    )

    await store.add(repo)
    assert await store.get(repo.id) == repo
    assert await store.get_by_source_uri(repo.source_uri) == repo
    assert await store.list() == [repo]

    repo.mark_collecting()
    await store.update(repo)
    fetched = await store.get(repo.id)
    assert fetched is not None
    assert fetched.status.value == "collecting"

    await store.delete(repo.id)
    assert await store.get(repo.id) is None
    assert await store.list() == []


@pytest.mark.asyncio
async def test_in_memory_store_get_and_lookup_of_missing_entity_returns_none() -> None:
    """Looking up an id or source URI that was never added should return None, not raise."""
    store = _InMemorySourceRepositoryStore()

    assert await store.get(uuid4()) is None
    assert await store.get_by_source_uri("nope") is None


class _SourceFileRepositoryStub(SourceFileRepository):
    """A minimal stub proving `SourceFileRepository`'s contract is implementable."""

    async def get(self, entity_id: UUID) -> SourceFile | None:
        """Always report no match; sufficient to prove the contract shape."""
        return None

    async def add(self, entity: SourceFile) -> None:
        """No-op add; sufficient to prove the contract shape."""
        return

    async def update(self, entity: SourceFile) -> None:
        """No-op update; sufficient to prove the contract shape."""
        return

    async def delete(self, entity_id: UUID) -> None:
        """No-op delete; sufficient to prove the contract shape."""
        return

    async def list_by_repository(self, repository_id: UUID) -> list[SourceFile]:
        """Always report an empty list; sufficient to prove the contract shape."""
        return []

    async def list(self) -> list[SourceFile]:
        """Always report an empty list; sufficient to prove the contract shape."""
        return []


@pytest.mark.asyncio
async def test_source_file_repository_extra_method_is_implementable() -> None:
    """A concrete `SourceFileRepository` must implement `list_by_repository`."""
    stub = _SourceFileRepositoryStub()

    assert await stub.list_by_repository(uuid4()) == []


class _AnalysisRunRepositoryStub(AnalysisRunRepository):
    """A minimal stub proving `AnalysisRunRepository`'s contract is implementable."""

    async def get(self, entity_id: UUID) -> AnalysisRun | None:
        """Always report no match; sufficient to prove the contract shape."""
        return None

    async def add(self, entity: AnalysisRun) -> None:
        """No-op add; sufficient to prove the contract shape."""
        return

    async def update(self, entity: AnalysisRun) -> None:
        """No-op update; sufficient to prove the contract shape."""
        return

    async def delete(self, entity_id: UUID) -> None:
        """No-op delete; sufficient to prove the contract shape."""
        return

    async def list_by_repository(self, repository_id: UUID) -> list[AnalysisRun]:
        """Always report an empty list; sufficient to prove the contract shape."""
        return []

    async def list(self) -> list[AnalysisRun]:
        """Always report an empty list; sufficient to prove the contract shape."""
        return []


@pytest.mark.asyncio
async def test_analysis_run_repository_extra_method_is_implementable() -> None:
    """A concrete `AnalysisRunRepository` must implement `list_by_repository`."""
    stub = _AnalysisRunRepositoryStub()

    assert await stub.list_by_repository(uuid4()) == []


class _FindingRepositoryStub(FindingRepository):
    """A minimal stub proving `FindingRepository`'s contract is implementable."""

    async def get(self, entity_id: UUID) -> Finding | None:
        """Always report no match; sufficient to prove the contract shape."""
        return None

    async def add(self, entity: Finding) -> None:
        """No-op add; sufficient to prove the contract shape."""
        return

    async def update(self, entity: Finding) -> None:
        """No-op update; sufficient to prove the contract shape."""
        return

    async def delete(self, entity_id: UUID) -> None:
        """No-op delete; sufficient to prove the contract shape."""
        return

    async def list_by_analysis_run(self, analysis_run_id: UUID) -> list[Finding]:
        """Always report an empty list; sufficient to prove the contract shape."""
        return []

    async def list(self) -> list[Finding]:
        """Always report an empty list; sufficient to prove the contract shape."""
        return []


@pytest.mark.asyncio
async def test_finding_repository_extra_method_is_implementable() -> None:
    """A concrete `FindingRepository` must implement `list_by_analysis_run`."""
    stub = _FindingRepositoryStub()

    assert await stub.list_by_analysis_run(uuid4()) == []
