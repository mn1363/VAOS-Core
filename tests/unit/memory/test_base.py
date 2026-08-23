"""Unit tests for `src.memory.base`."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from src.core.exceptions import ValidationError
from src.core.protocols import SupportsAsyncClose
from src.memory.base import (
    MemoryQuery,
    MemoryQueryResult,
    MemoryRecord,
    MemoryStore,
    matches_query,
)

RECORD_A = UUID("11111111-1111-1111-1111-111111111111")
RECORD_B = UUID("22222222-2222-2222-2222-222222222222")
RECORD_C = UUID("33333333-3333-3333-3333-333333333333")
ENTITY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ENTITY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _record(
    record_id: UUID = RECORD_A,
    memory_type: str = "note",
    content: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    entity_id: UUID | None = None,
) -> MemoryRecord:
    """Build a minimal, valid `MemoryRecord` for reuse across tests."""
    return MemoryRecord(
        id=record_id,
        memory_type=memory_type,
        content=content if content is not None else {"text": "hello"},
        metadata=metadata if metadata is not None else {},
        entity_id=entity_id,
    )


# --- MemoryRecord --------------------------------------------------------------------------------


def test_memory_record_defaults_metadata_to_empty() -> None:
    """`MemoryRecord` should default `metadata` to an empty dict."""
    assert MemoryRecord(id=RECORD_A, memory_type="note", content={}).metadata == {}


def test_memory_record_defaults_entity_id_to_none() -> None:
    """`MemoryRecord` should default `entity_id` to None -- knowledge need not concern a single
    entity."""
    assert MemoryRecord(id=RECORD_A, memory_type="note", content={}).entity_id is None


def test_memory_record_is_frozen() -> None:
    """`MemoryRecord` should be immutable once constructed."""
    record = _record()
    with pytest.raises(AttributeError):
        record.memory_type = "other"  # type: ignore[misc]


def test_memory_record_rejects_empty_memory_type() -> None:
    """A blank `memory_type` should raise."""
    with pytest.raises(ValidationError):
        _record(memory_type="")


def test_memory_record_rejects_whitespace_only_memory_type() -> None:
    """A whitespace-only `memory_type` should raise."""
    with pytest.raises(ValidationError):
        _record(memory_type="   ")


def test_memory_record_equality_is_by_value() -> None:
    """Two records with identical fields should be equal (DTO-style value equality)."""
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)
    first = MemoryRecord(
        id=RECORD_A, memory_type="note", content={}, created_at=fixed_time, updated_at=fixed_time
    )
    second = MemoryRecord(
        id=RECORD_A, memory_type="note", content={}, created_at=fixed_time, updated_at=fixed_time
    )
    assert first == second


def test_memory_record_distinguishes_own_id_from_entity_id() -> None:
    """`id` (the memory record's own identity) and `entity_id` (the associated entity) are
    independent fields, and may legitimately differ."""
    record = _record(record_id=RECORD_A, entity_id=ENTITY_A)
    assert record.id == RECORD_A
    assert record.entity_id == ENTITY_A
    assert record.id != record.entity_id


def test_memory_record_content_is_preserved() -> None:
    """Arbitrary structured content passed at construction should be stored unchanged."""
    record = _record(content={"decision": "use SQLite", "confidence": 0.8})
    assert record.content == {"decision": "use SQLite", "confidence": 0.8}


def test_memory_record_metadata_is_preserved() -> None:
    """Arbitrary metadata passed at construction should be stored unchanged."""
    record = _record(metadata={"author": "phase9-analyzer"})
    assert record.metadata == {"author": "phase9-analyzer"}


def test_memory_record_timestamps_default_independently() -> None:
    """`created_at`/`updated_at` should default via their own factory, not share one instant."""
    record = MemoryRecord(id=RECORD_A, memory_type="note", content={})
    assert record.created_at.tzinfo is not None
    assert record.updated_at.tzinfo is not None


# --- MemoryQuery ----------------------------------------------------------------------------------


def test_memory_query_defaults() -> None:
    """`MemoryQuery` should default every filter to unset and `limit` to 100."""
    query = MemoryQuery()
    assert query.memory_type is None
    assert query.entity_id is None
    assert query.metadata_filter == {}
    assert query.limit == 100


def test_memory_query_rejects_empty_memory_type() -> None:
    """A `memory_type` given as an empty string should raise."""
    with pytest.raises(ValidationError):
        MemoryQuery(memory_type="")


def test_memory_query_rejects_zero_limit() -> None:
    """A `limit` of zero should raise."""
    with pytest.raises(ValidationError):
        MemoryQuery(limit=0)


def test_memory_query_rejects_negative_limit() -> None:
    """A negative `limit` should raise."""
    with pytest.raises(ValidationError):
        MemoryQuery(limit=-5)


# --- matches_query ---------------------------------------------------------------------------------


def test_matches_query_with_no_constraints_matches_everything() -> None:
    """A fully-unconstrained query should match any record."""
    assert matches_query(_record(), MemoryQuery()) is True


def test_matches_query_filters_by_memory_type() -> None:
    """A `memory_type` constraint should only match records of that exact type."""
    note = _record(memory_type="note")
    decision = _record(memory_type="decision")
    query = MemoryQuery(memory_type="decision")
    assert matches_query(note, query) is False
    assert matches_query(decision, query) is True


def test_matches_query_filters_by_entity_id() -> None:
    """An `entity_id` constraint should only match records tied to that exact entity."""
    tied = _record(entity_id=ENTITY_A)
    other = _record(entity_id=ENTITY_B)
    untied = _record(entity_id=None)
    query = MemoryQuery(entity_id=ENTITY_A)
    assert matches_query(tied, query) is True
    assert matches_query(other, query) is False
    assert matches_query(untied, query) is False


def test_matches_query_filters_by_metadata() -> None:
    """A `metadata_filter` should require every given key/value pair to match exactly."""
    record = _record(metadata={"author": "alice", "confidence": "high"})
    assert matches_query(record, MemoryQuery(metadata_filter={"author": "alice"})) is True
    assert (
        matches_query(
            record, MemoryQuery(metadata_filter={"author": "alice", "confidence": "high"})
        )
        is True
    )
    assert matches_query(record, MemoryQuery(metadata_filter={"author": "bob"})) is False


def test_matches_query_metadata_filter_key_absent_does_not_match() -> None:
    """A `metadata_filter` key absent from the record's own metadata should not match."""
    record = _record(metadata={"author": "alice"})
    assert matches_query(record, MemoryQuery(metadata_filter={"confidence": "high"})) is False


# --- MemoryQueryResult -----------------------------------------------------------------------------


def test_memory_query_result_defaults_to_empty() -> None:
    """A `MemoryQueryResult` with no records should construct cleanly."""
    assert MemoryQueryResult().record_count == 0


def test_memory_query_result_accepts_correctly_ordered_records() -> None:
    """Records sorted by ascending `id` should construct cleanly."""
    result = MemoryQueryResult(records=(_record(RECORD_A), _record(RECORD_B), _record(RECORD_C)))
    assert result.record_count == 3


def test_memory_query_result_rejects_records_out_of_id_order() -> None:
    """Records not sorted by ascending `id` should raise."""
    with pytest.raises(ValidationError):
        MemoryQueryResult(records=(_record(RECORD_C), _record(RECORD_A)))


def test_memory_query_result_rejects_duplicate_ids() -> None:
    """Two records sharing the same `id` should raise."""
    with pytest.raises(ValidationError):
        MemoryQueryResult(records=(_record(RECORD_A), _record(RECORD_A)))


def test_memory_query_result_top_returns_prefix() -> None:
    """`top(count)` should return the first `count` records, in existing order."""
    result = MemoryQueryResult(records=(_record(RECORD_A), _record(RECORD_B), _record(RECORD_C)))
    assert [record.id for record in result.top(2)] == [RECORD_A, RECORD_B]


def test_memory_query_result_top_beyond_count_returns_everything() -> None:
    """`top(count)` with `count` greater than `record_count` should return every record."""
    result = MemoryQueryResult(records=(_record(RECORD_A), _record(RECORD_B)))
    assert len(result.top(10)) == 2


def test_memory_query_result_top_rejects_negative_count() -> None:
    """A negative `count` passed to `top` should raise."""
    with pytest.raises(ValidationError):
        MemoryQueryResult().top(-1)


# --- MemoryStore Port -------------------------------------------------------------------------------


def test_memory_store_cannot_be_instantiated_directly() -> None:
    """The abstract `MemoryStore` Port must not be instantiable."""
    with pytest.raises(TypeError):
        MemoryStore()  # type: ignore[abstract]


class _InMemoryMemoryStore(MemoryStore):
    """A minimal, fully-working in-memory implementation.

    Used only to prove that `MemoryStore`'s contract is coherent and genuinely implementable --
    not a production adapter, matching `tests/unit/vector/test_base.py`'s own
    `_InMemoryVectorStore` precedent for exactly this purpose.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._items: dict[UUID, MemoryRecord] = {}
        self.closed = False

    async def upsert(self, record: MemoryRecord) -> None:
        """Store `record`, overwriting any existing record sharing its `id`."""
        self._items[record.id] = record

    async def get(self, record_id: UUID) -> MemoryRecord | None:
        """Retrieve a record by id, or None if not present."""
        return self._items.get(record_id)

    async def delete(self, record_id: UUID) -> None:
        """Remove a record by id, if present."""
        self._items.pop(record_id, None)

    async def exists(self, record_id: UUID) -> bool:
        """Report whether a record with this id is currently stored."""
        return record_id in self._items

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        """Return every stored record matching `request`, sorted by id and truncated to
        `request.limit` -- a deliberately simple reference implementation exercising
        `matches_query` and `MemoryQueryResult`'s own ordering contract."""
        candidates = [record for record in self._items.values() if matches_query(record, request)]
        ordered = tuple(sorted(candidates, key=lambda record: str(record.id)))
        return MemoryQueryResult(records=ordered[: request.limit])

    async def aclose(self) -> None:
        """Mark this store as closed."""
        self.closed = True


@pytest.mark.asyncio
async def test_in_memory_memory_store_round_trip() -> None:
    """A concrete `MemoryStore` should support the full upsert/get/exists/delete contract."""
    store = _InMemoryMemoryStore()
    record = _record()

    assert await store.exists(record.id) is False
    await store.upsert(record)
    assert await store.get(record.id) == record
    assert await store.exists(record.id) is True

    await store.delete(record.id)
    assert await store.get(record.id) is None
    assert await store.exists(record.id) is False


@pytest.mark.asyncio
async def test_in_memory_memory_store_delete_is_a_no_op_for_a_missing_record() -> None:
    """Deleting a `record_id` with no matching record should not raise."""
    store = _InMemoryMemoryStore()
    await store.delete(RECORD_A)


@pytest.mark.asyncio
async def test_in_memory_memory_store_upsert_overwrites_same_id() -> None:
    """Upserting a record sharing an existing `id` should overwrite it."""
    await_store = _InMemoryMemoryStore()
    await await_store.upsert(_record(content={"v": 1}))
    await await_store.upsert(_record(content={"v": 2}))
    stored = await await_store.get(RECORD_A)
    assert stored is not None
    assert stored.content == {"v": 2}


@pytest.mark.asyncio
async def test_in_memory_memory_store_query_returns_deterministic_order() -> None:
    """`query` should return matches ordered by ascending id regardless of insertion order."""
    store = _InMemoryMemoryStore()
    await store.upsert(_record(RECORD_C))
    await store.upsert(_record(RECORD_A))
    await store.upsert(_record(RECORD_B))

    result = await store.query(MemoryQuery())

    assert [record.id for record in result.records] == [RECORD_A, RECORD_B, RECORD_C]


@pytest.mark.asyncio
async def test_in_memory_memory_store_query_respects_limit() -> None:
    """`query` should return at most `request.limit` records."""
    store = _InMemoryMemoryStore()
    await store.upsert(_record(RECORD_A))
    await store.upsert(_record(RECORD_B))
    await store.upsert(_record(RECORD_C))

    result = await store.query(MemoryQuery(limit=2))

    assert result.record_count == 2


@pytest.mark.asyncio
async def test_in_memory_memory_store_query_applies_memory_type_filter() -> None:
    """`query` should only return records matching a given `memory_type`."""
    store = _InMemoryMemoryStore()
    await store.upsert(_record(RECORD_A, memory_type="note"))
    await store.upsert(_record(RECORD_B, memory_type="decision"))

    result = await store.query(MemoryQuery(memory_type="decision"))

    assert [record.id for record in result.records] == [RECORD_B]


@pytest.mark.asyncio
async def test_in_memory_memory_store_query_applies_entity_id_filter() -> None:
    """`query` should only return records matching a given `entity_id`."""
    store = _InMemoryMemoryStore()
    await store.upsert(_record(RECORD_A, entity_id=ENTITY_A))
    await store.upsert(_record(RECORD_B, entity_id=ENTITY_B))

    result = await store.query(MemoryQuery(entity_id=ENTITY_A))

    assert [record.id for record in result.records] == [RECORD_A]


@pytest.mark.asyncio
async def test_in_memory_memory_store_query_applies_metadata_filter() -> None:
    """`query` should only return records matching every `metadata_filter` entry."""
    store = _InMemoryMemoryStore()
    await store.upsert(_record(RECORD_A, metadata={"lang": "py"}))
    await store.upsert(_record(RECORD_B, metadata={"lang": "go"}))

    result = await store.query(MemoryQuery(metadata_filter={"lang": "py"}))

    assert [record.id for record in result.records] == [RECORD_A]


@pytest.mark.asyncio
async def test_in_memory_memory_store_query_with_no_matches_returns_empty_result() -> None:
    """`query` should return an empty `MemoryQueryResult` when nothing matches."""
    store = _InMemoryMemoryStore()
    await store.upsert(_record(RECORD_A, memory_type="note"))

    result = await store.query(MemoryQuery(memory_type="decision"))

    assert result.record_count == 0


@pytest.mark.asyncio
async def test_in_memory_memory_store_aclose_releases_the_store() -> None:
    """`aclose` should run without raising and reflect the store's closed state."""
    store = _InMemoryMemoryStore()
    assert store.closed is False
    await store.aclose()
    assert store.closed is True


def test_in_memory_memory_store_satisfies_supports_async_close() -> None:
    """A fully-implemented `MemoryStore` should structurally satisfy `SupportsAsyncClose`,
    proving `aclose` integrates with `core.protocols` without formally inheriting from it."""
    assert isinstance(_InMemoryMemoryStore(), SupportsAsyncClose)
