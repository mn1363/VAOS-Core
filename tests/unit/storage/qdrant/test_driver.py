"""Unit tests for `src.storage.qdrant.driver`.

Uses `FakeQdrantClient`, an in-memory double implementing the subset of
`qdrant_client.AsyncQdrantClient`'s calling convention this driver actually uses
(`collection_exists`, `create_collection`, `upsert`, `retrieve`, `delete`, `search`, `close`) --
not a live Qdrant server, per this phase's "unit tests must not require live external services"
requirement.

The module-level `pytest.importorskip("qdrant_client")` below matters beyond this one file:
without it, `src.storage.qdrant.driver`'s own unconditional `import qdrant_client` (not yet a
declared project dependency -- see that module's docstring) would turn a missing `qdrant_client`
into a hard *collection* error, which aborts pytest's entire session by default -- not just skip
this file. `importorskip` turns it into a clean per-file skip instead, matching
`tests/unit/storage/test_imports.py`'s own precedent for the same reason.
"""

import math
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

pytest.importorskip("qdrant_client", reason="qdrant-client is not yet a declared project dependency")

from qdrant_client.http import models
from src.core.exceptions import ValidationError
from src.storage.qdrant.driver import QdrantOperationError, QdrantVectorStore
from src.vector.base import (
    SimilaritySearchRequest,
    VectorDimensionMismatchError,
    VectorRecord,
)

ENTITY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ENTITY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Raw cosine similarity between two vectors, for the fake's own search ranking."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)


class FakeQdrantClient:
    """An in-memory double for the subset of `AsyncQdrantClient` this driver calls."""

    def __init__(self) -> None:
        self.collections: set[str] = set()
        self.points: dict[str, models.PointStruct] = {}
        self.closed = False

    async def collection_exists(self, collection_name: str, **kwargs: Any) -> bool:
        return collection_name in self.collections

    async def create_collection(
        self, collection_name: str, vectors_config: Any, **kwargs: Any
    ) -> bool:
        self.collections.add(collection_name)
        return True

    async def upsert(
        self, collection_name: str, points: list[models.PointStruct], **kwargs: Any
    ) -> Any:
        for point in points:
            self.points[str(point.id)] = point
        return SimpleNamespace(status="completed")

    async def retrieve(
        self,
        collection_name: str,
        ids: list[str],
        with_payload: bool = True,
        with_vectors: bool = False,
        **kwargs: Any,
    ) -> list[Any]:
        out = []
        for point_id in ids:
            point = self.points.get(str(point_id))
            if point is not None:
                out.append(
                    SimpleNamespace(
                        id=point.id,
                        payload=dict(point.payload or {}) if with_payload else None,
                        vector=self._flat_vector(point) if with_vectors else None,
                    )
                )
        return out

    async def delete(self, collection_name: str, points_selector: list[str], **kwargs: Any) -> Any:
        for point_id in points_selector:
            self.points.pop(str(point_id), None)
        return SimpleNamespace(status="completed")

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        query_filter: models.Filter | None = None,
        limit: int = 10,
        with_payload: bool = True,
        with_vectors: bool = True,
        **kwargs: Any,
    ) -> list[Any]:
        results = []
        for point in self.points.values():
            payload = dict(point.payload or {})
            if query_filter is not None and not self._matches_filter(payload, query_filter):
                continue
            vector = self._flat_vector(point)
            score = _cosine_similarity(vector, query_vector)
            results.append(
                SimpleNamespace(id=point.id, score=score, payload=payload, vector=vector)
            )
        results.sort(key=lambda r: -r.score)
        return results[:limit]

    @staticmethod
    def _flat_vector(point: models.PointStruct) -> list[float]:
        """Return `point.vector` as a flat `list[float]`.

        This fake only ever stores a flat vector (whatever `QdrantVectorStore.upsert` passed, a
        plain `list(record.embedding)`) -- never Qdrant's named- or sparse-vector shapes -- so
        this narrows `PointStruct.vector`'s broader declared type down to what this fake
        actually holds.
        """
        assert isinstance(point.vector, list)
        return point.vector

    @staticmethod
    def _matches_filter(payload: dict[str, Any], query_filter: models.Filter) -> bool:
        """Check `payload` against every `FieldCondition`/`MatchValue` pair in `must`.

        This fake only needs to understand the exact `Filter` shape
        `QdrantVectorStore._build_filter` itself ever constructs -- a flat `must` list of
        `FieldCondition(key=..., match=MatchValue(value=...))` -- so any other condition or
        match type narrows to "not matched" rather than being handled generically.
        """
        for condition in query_filter.must or []:
            if not isinstance(condition, models.FieldCondition):
                return False
            if not isinstance(condition.match, models.MatchValue):
                return False
            if payload.get(condition.key) != condition.match.value:
                return False
        return True

    async def close(self, **kwargs: Any) -> None:
        self.closed = True


def _record(
    record_id: UUID | None = None,
    entity_id: UUID = ENTITY_A,
    embedding: tuple[float, ...] = (1.0, 0.0, 0.0),
    metadata: dict[str, Any] | None = None,
) -> VectorRecord:
    """Build a `VectorRecord` for reuse across tests."""
    return VectorRecord(
        id=record_id or uuid4(),
        entity_id=entity_id,
        embedding=embedding,
        metadata=metadata or {},
    )


@pytest.fixture
def client() -> FakeQdrantClient:
    """A fresh `FakeQdrantClient` for each test."""
    return FakeQdrantClient()


# --- Construction ------------------------------------------------------------------------------


def test_construction_performs_no_network_call(client: FakeQdrantClient) -> None:
    """Constructing the store should not touch the client at all -- no hidden network call
    during `__init__`, matching this phase's explicit requirement."""
    QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    assert client.collections == set()
    assert client.points == {}


def test_rejects_blank_collection_name(client: FakeQdrantClient) -> None:
    """An empty or whitespace-only `collection_name` should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        QdrantVectorStore(client, collection_name="   ", vector_size=3)


def test_rejects_non_positive_vector_size(client: FakeQdrantClient) -> None:
    """A `vector_size` of zero or negative should raise `ValidationError`."""
    with pytest.raises(ValidationError):
        QdrantVectorStore(client, collection_name="vaos_files", vector_size=0)


# --- ensure_collection ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_collection_creates_it_with_no_hardcoded_name(
    client: FakeQdrantClient,
) -> None:
    """`ensure_collection` should create a collection under exactly the injected name."""
    store = QdrantVectorStore(client, collection_name="my_custom_collection", vector_size=3)

    await store.ensure_collection()

    assert "my_custom_collection" in client.collections


@pytest.mark.asyncio
async def test_ensure_collection_is_idempotent(client: FakeQdrantClient) -> None:
    """Calling `ensure_collection` twice should not raise."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    await store.ensure_collection()
    await store.ensure_collection()  # should not raise

    assert client.collections == {"vaos_files"}


# --- upsert / get --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_then_get_round_trips_the_full_record(client: FakeQdrantClient) -> None:
    """`upsert` then `get` should reconstruct the exact original `VectorRecord`."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    record = _record(embedding=(1.0, 2.0, 3.0), metadata={"path": "a.py", "chunk": 0})

    await store.upsert(record)
    fetched = await store.get(record.id)

    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.entity_id == record.entity_id
    assert fetched.embedding == record.embedding
    assert fetched.metadata == record.metadata


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_id(client: FakeQdrantClient) -> None:
    """`get` for an id that was never upserted should return None."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    assert await store.get(uuid4()) is None


@pytest.mark.asyncio
async def test_upsert_overwrites_an_existing_record_with_the_same_id(
    client: FakeQdrantClient,
) -> None:
    """A second `upsert` with the same `record.id` should overwrite, not duplicate."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    record_id = uuid4()
    await store.upsert(_record(record_id=record_id, embedding=(1.0, 0.0, 0.0)))

    await store.upsert(_record(record_id=record_id, embedding=(0.0, 1.0, 0.0)))

    fetched = await store.get(record_id)
    assert fetched is not None
    assert fetched.embedding == (0.0, 1.0, 0.0)
    assert len(client.points) == 1


@pytest.mark.asyncio
async def test_upsert_rejects_a_dimension_mismatch(client: FakeQdrantClient) -> None:
    """`upsert` with an embedding of the wrong size should raise
    `VectorDimensionMismatchError`, not silently store it."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    with pytest.raises(VectorDimensionMismatchError):
        await store.upsert(_record(embedding=(1.0, 2.0)))

    assert client.points == {}


@pytest.mark.asyncio
async def test_deterministic_metadata_mapping_round_trip(client: FakeQdrantClient) -> None:
    """Every metadata key/value should survive `upsert`/`get` exactly, distinct from the
    reserved `entity_id` payload key."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    record = _record(metadata={"relative_path": "src/a.py", "chunk_index": 2, "lang": "python"})

    await store.upsert(record)
    fetched = await store.get(record.id)

    assert fetched is not None
    assert fetched.metadata == {
        "relative_path": "src/a.py",
        "chunk_index": 2,
        "lang": "python",
    }
    assert "entity_id" not in fetched.metadata


# --- delete / exists -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_the_record(client: FakeQdrantClient) -> None:
    """After `delete`, `get` should return None."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    record = _record()
    await store.upsert(record)

    await store.delete(record.id)

    assert await store.get(record.id) is None


@pytest.mark.asyncio
async def test_delete_unknown_id_is_a_no_op(client: FakeQdrantClient) -> None:
    """`delete` on an id that was never upserted should not raise."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    await store.delete(uuid4())  # should not raise


@pytest.mark.asyncio
async def test_exists_true_after_upsert(client: FakeQdrantClient) -> None:
    """`exists` should report True for a record that was upserted."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    record = _record()
    await store.upsert(record)

    assert await store.exists(record.id) is True


@pytest.mark.asyncio
async def test_exists_false_for_unknown_id(client: FakeQdrantClient) -> None:
    """`exists` should report False for an id that was never upserted."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    assert await store.exists(uuid4()) is False


@pytest.mark.asyncio
async def test_exists_false_after_delete(client: FakeQdrantClient) -> None:
    """`exists` should report False immediately after `delete`."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    record = _record()
    await store.upsert(record)
    await store.delete(record.id)

    assert await store.exists(record.id) is False


# --- search ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_orders_by_similarity_descending(client: FakeQdrantClient) -> None:
    """The closest record to the query should be the first match."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    closest = _record(embedding=(1.0, 0.0, 0.0))
    farther = _record(embedding=(0.0, 1.0, 0.0))
    await store.upsert(closest)
    await store.upsert(farther)

    result = await store.search(SimilaritySearchRequest(query_embedding=(1.0, 0.0, 0.0), limit=5))

    assert result.match_count == 2
    assert result.matches[0].record.id == closest.id
    assert result.matches[0].score > result.matches[1].score


@pytest.mark.asyncio
async def test_search_scores_are_normalized_to_zero_one(client: FakeQdrantClient) -> None:
    """Every match's `score` should fall within `[0.0, 1.0]`, even for an opposite-direction
    vector whose raw cosine similarity is negative."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    opposite = _record(embedding=(-1.0, 0.0, 0.0))
    await store.upsert(opposite)

    result = await store.search(SimilaritySearchRequest(query_embedding=(1.0, 0.0, 0.0), limit=5))

    assert result.match_count == 1
    assert 0.0 <= result.matches[0].score <= 1.0


@pytest.mark.asyncio
async def test_search_respects_limit(client: FakeQdrantClient) -> None:
    """`search` should return at most `request.limit` matches."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    for i in range(5):
        await store.upsert(_record(embedding=(1.0, float(i), 0.0)))

    result = await store.search(SimilaritySearchRequest(query_embedding=(1.0, 0.0, 0.0), limit=2))

    assert result.match_count == 2


@pytest.mark.asyncio
async def test_search_applies_metadata_filter(client: FakeQdrantClient) -> None:
    """`search` should only return records matching every `metadata_filter` key/value pair."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    matching = _record(embedding=(1.0, 0.0, 0.0), metadata={"lang": "python"})
    other = _record(embedding=(1.0, 0.0, 0.0), metadata={"lang": "rust"})
    await store.upsert(matching)
    await store.upsert(other)

    result = await store.search(
        SimilaritySearchRequest(
            query_embedding=(1.0, 0.0, 0.0), limit=5, metadata_filter={"lang": "python"}
        )
    )

    assert result.match_count == 1
    assert result.matches[0].record.id == matching.id


@pytest.mark.asyncio
async def test_search_on_empty_collection_returns_empty_result(client: FakeQdrantClient) -> None:
    """`search` against an empty collection should return an empty result, not raise."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    result = await store.search(SimilaritySearchRequest(query_embedding=(1.0, 0.0, 0.0), limit=5))

    assert result.match_count == 0
    assert result.matches == ()


@pytest.mark.asyncio
async def test_search_rejects_a_dimension_mismatch(client: FakeQdrantClient) -> None:
    """`search` with a query embedding of the wrong size should raise
    `VectorDimensionMismatchError`."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    with pytest.raises(VectorDimensionMismatchError):
        await store.search(SimilaritySearchRequest(query_embedding=(1.0, 2.0)))


@pytest.mark.asyncio
async def test_search_result_is_deterministic_across_repeated_calls(
    client: FakeQdrantClient,
) -> None:
    """Two identical searches against unchanged data should return identically ordered
    results."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    for i in range(4):
        await store.upsert(_record(embedding=(1.0, float(i) * 0.1, 0.0)))
    request = SimilaritySearchRequest(query_embedding=(1.0, 0.0, 0.0), limit=10)

    first = await store.search(request)
    second = await store.search(request)

    assert [m.record.id for m in first.matches] == [m.record.id for m in second.matches]
    assert [m.score for m in first.matches] == [m.score for m in second.matches]


# --- Invalid inputs / client errors ---------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_wraps_client_failure(client: FakeQdrantClient) -> None:
    """A client failure during `upsert` should surface as `QdrantOperationError`."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("network unreachable")

    client.upsert = _boom  # type: ignore[method-assign]

    with pytest.raises(QdrantOperationError):
        await store.upsert(_record())


@pytest.mark.asyncio
async def test_search_wraps_client_failure(client: FakeQdrantClient) -> None:
    """A client failure during `search` should surface as `QdrantOperationError`."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("network unreachable")

    client.search = _boom  # type: ignore[method-assign]

    with pytest.raises(QdrantOperationError):
        await store.search(SimilaritySearchRequest(query_embedding=(1.0, 0.0, 0.0)))


@pytest.mark.asyncio
async def test_get_raises_on_a_point_missing_the_reserved_entity_id_key(
    client: FakeQdrantClient,
) -> None:
    """A stored point without this driver's own reserved `entity_id` payload key -- i.e. one
    not written by this driver -- should raise `QdrantOperationError`, not a raw `KeyError`."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)
    foreign_point = models.PointStruct(id=str(uuid4()), vector=[1.0, 0.0, 0.0], payload={})
    client.points[str(foreign_point.id)] = foreign_point

    with pytest.raises(QdrantOperationError):
        await store.get(UUID(str(foreign_point.id)))


# --- Lifecycle -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_closes_the_underlying_client(client: FakeQdrantClient) -> None:
    """`aclose` should release the injected client's own resources."""
    store = QdrantVectorStore(client, collection_name="vaos_files", vector_size=3)

    await store.aclose()

    assert client.closed is True
