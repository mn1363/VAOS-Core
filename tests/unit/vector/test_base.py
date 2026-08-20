"""Unit tests for `src.vector.base`."""

import math
from uuid import UUID

import pytest
from src.core.exceptions import ValidationError
from src.core.protocols import SupportsAsyncClose
from src.vector.base import (
    SimilaritySearchMatch,
    SimilaritySearchRequest,
    SimilaritySearchResult,
    VectorDimensionMismatchError,
    VectorRecord,
    VectorStore,
    require_matching_dimensions,
)

RECORD_A = UUID("11111111-1111-1111-1111-111111111111")
RECORD_B = UUID("22222222-2222-2222-2222-222222222222")
RECORD_C = UUID("33333333-3333-3333-3333-333333333333")
ENTITY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _record(
    record_id: UUID = RECORD_A,
    entity_id: UUID = ENTITY_A,
    embedding: tuple[float, ...] = (1.0, 0.0, 0.0),
) -> VectorRecord:
    """Build a minimal, valid `VectorRecord` for reuse across tests."""
    return VectorRecord(id=record_id, entity_id=entity_id, embedding=embedding)


# --- VectorRecord ------------------------------------------------------------------------------


def test_vector_record_defaults_metadata_to_empty() -> None:
    """`VectorRecord` should default `metadata` to an empty dict."""
    assert _record().metadata == {}


def test_vector_record_is_frozen() -> None:
    """`VectorRecord` should be immutable once constructed."""
    record = _record()
    with pytest.raises(AttributeError):
        record.embedding = (1.0,)  # type: ignore[misc]


def test_vector_record_reports_dimensions() -> None:
    """`dimensions` should equal the length of `embedding`."""
    assert _record(embedding=(1.0, 2.0, 3.0, 4.0)).dimensions == 4


def test_vector_record_rejects_empty_embedding() -> None:
    """An empty `embedding` should raise."""
    with pytest.raises(ValidationError):
        _record(embedding=())


def test_vector_record_rejects_nan_component() -> None:
    """An embedding containing NaN should raise."""
    with pytest.raises(ValidationError):
        _record(embedding=(1.0, math.nan))


def test_vector_record_rejects_infinite_component() -> None:
    """An embedding containing an infinite value should raise."""
    with pytest.raises(ValidationError):
        _record(embedding=(1.0, math.inf))


def test_vector_record_equality_is_by_value() -> None:
    """Two records with identical fields should be equal (DTO-style value equality)."""
    assert _record() == _record()


def test_vector_record_distinguishes_own_id_from_entity_id() -> None:
    """`id` (the vector record's own identity) and `entity_id` (the associated entity) are
    independent fields, and may legitimately differ."""
    record = _record(record_id=RECORD_A, entity_id=ENTITY_A)
    assert record.id == RECORD_A
    assert record.entity_id == ENTITY_A
    assert record.id != record.entity_id


def test_vector_record_metadata_is_preserved() -> None:
    """Arbitrary metadata passed at construction should be stored unchanged."""
    record = VectorRecord(
        id=RECORD_A, entity_id=ENTITY_A, embedding=(1.0,), metadata={"chunk_index": 3}
    )
    assert record.metadata == {"chunk_index": 3}


# --- SimilaritySearchRequest ---------------------------------------------------------------------


def test_similarity_search_request_defaults() -> None:
    """`SimilaritySearchRequest` should default `limit` to 10 and `metadata_filter` to empty."""
    request = SimilaritySearchRequest(query_embedding=(1.0, 0.0))
    assert request.limit == 10
    assert request.metadata_filter == {}


def test_similarity_search_request_reports_dimensions() -> None:
    """`dimensions` should equal the length of `query_embedding`."""
    assert SimilaritySearchRequest(query_embedding=(1.0, 2.0, 3.0)).dimensions == 3


def test_similarity_search_request_rejects_empty_query_embedding() -> None:
    """An empty `query_embedding` should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchRequest(query_embedding=())


def test_similarity_search_request_rejects_non_finite_component() -> None:
    """A `query_embedding` containing a non-finite value should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchRequest(query_embedding=(1.0, math.nan))


def test_similarity_search_request_rejects_zero_limit() -> None:
    """A `limit` of zero should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchRequest(query_embedding=(1.0,), limit=0)


def test_similarity_search_request_rejects_negative_limit() -> None:
    """A negative `limit` should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchRequest(query_embedding=(1.0,), limit=-5)


# --- SimilaritySearchMatch / SimilaritySearchResult -----------------------------------------------


def test_similarity_search_match_accepts_boundary_scores() -> None:
    """`score` of exactly 0.0 and 1.0 should both be accepted."""
    assert SimilaritySearchMatch(record=_record(), score=0.0).score == 0.0
    assert SimilaritySearchMatch(record=_record(), score=1.0).score == 1.0


def test_similarity_search_match_rejects_score_below_zero() -> None:
    """A `score` below 0.0 should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchMatch(record=_record(), score=-0.1)


def test_similarity_search_match_rejects_score_above_one() -> None:
    """A `score` above 1.0 should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchMatch(record=_record(), score=1.1)


def test_similarity_search_result_defaults_to_empty() -> None:
    """A `SimilaritySearchResult` with no matches should construct cleanly."""
    assert SimilaritySearchResult().match_count == 0


def test_similarity_search_result_accepts_correctly_ordered_matches() -> None:
    """Matches sorted by `(-score, record.id)` should construct cleanly."""
    result = SimilaritySearchResult(
        matches=(
            SimilaritySearchMatch(record=_record(RECORD_A), score=0.9),
            SimilaritySearchMatch(record=_record(RECORD_B), score=0.5),
            SimilaritySearchMatch(record=_record(RECORD_C), score=0.5),
        )
    )
    assert result.match_count == 3


def test_similarity_search_result_rejects_matches_out_of_score_order() -> None:
    """Matches not sorted by descending `score` should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchResult(
            matches=(
                SimilaritySearchMatch(record=_record(RECORD_A), score=0.5),
                SimilaritySearchMatch(record=_record(RECORD_B), score=0.9),
            )
        )


def test_similarity_search_result_rejects_ties_out_of_id_order() -> None:
    """Tied scores not tie-broken by ascending `record.id` should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchResult(
            matches=(
                SimilaritySearchMatch(record=_record(RECORD_B), score=0.5),
                SimilaritySearchMatch(record=_record(RECORD_A), score=0.5),
            )
        )


def test_similarity_search_result_rejects_duplicate_records() -> None:
    """Two matches for the same `record.id` should raise."""
    with pytest.raises(ValidationError):
        SimilaritySearchResult(
            matches=(
                SimilaritySearchMatch(record=_record(RECORD_A), score=0.9),
                SimilaritySearchMatch(record=_record(RECORD_A), score=0.1),
            )
        )


def _sample_result() -> SimilaritySearchResult:
    """Build a small, valid three-match `SimilaritySearchResult` for reuse across tests."""
    return SimilaritySearchResult(
        matches=(
            SimilaritySearchMatch(record=_record(RECORD_A), score=0.9),
            SimilaritySearchMatch(record=_record(RECORD_B), score=0.5),
            SimilaritySearchMatch(record=_record(RECORD_C), score=0.1),
        )
    )


def test_similarity_search_result_top_returns_the_first_n_matches() -> None:
    """`top` should return the `count` highest-scoring matches, in order."""
    result = _sample_result()
    assert [match.record.id for match in result.top(2)] == [RECORD_A, RECORD_B]


def test_similarity_search_result_top_beyond_length_returns_everything() -> None:
    """`top` given a `count` larger than `match_count` should return every match."""
    assert len(_sample_result().top(100)) == 3


def test_similarity_search_result_top_rejects_negative_count() -> None:
    """`top` given a negative `count` should raise."""
    with pytest.raises(ValidationError):
        _sample_result().top(-1)


# --- require_matching_dimensions ----------------------------------------------------------------


def test_require_matching_dimensions_returns_records_unchanged() -> None:
    """Given records that all match the expected dimensionality, the sequence passes through."""
    records = [_record(RECORD_A, embedding=(1.0, 2.0)), _record(RECORD_B, embedding=(3.0, 4.0))]
    assert require_matching_dimensions(records, dimensions=2) is records


def test_require_matching_dimensions_rejects_a_mismatched_record() -> None:
    """A record whose `dimensions` differs from the expected value should raise."""
    records = [_record(RECORD_A, embedding=(1.0, 2.0)), _record(RECORD_B, embedding=(3.0,))]
    with pytest.raises(VectorDimensionMismatchError):
        require_matching_dimensions(records, dimensions=2)


def test_vector_dimension_mismatch_error_is_a_validation_error() -> None:
    """`VectorDimensionMismatchError` should be catchable as a `ValidationError`."""
    with pytest.raises(ValidationError):
        require_matching_dimensions([_record(embedding=(1.0,))], dimensions=5)


# --- VectorStore Port ----------------------------------------------------------------------------


def test_vector_store_cannot_be_instantiated_directly() -> None:
    """The abstract `VectorStore` Port must not be instantiable."""
    with pytest.raises(TypeError):
        VectorStore()  # type: ignore[abstract]


class _InMemoryVectorStore(VectorStore):
    """A minimal, fully-working in-memory implementation.

    Used only to prove that `VectorStore`'s contract is coherent and genuinely implementable --
    not a production adapter. Enforces a fixed embedding dimensionality, established by whichever
    record is upserted first, to exercise `VectorDimensionMismatchError`.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory store with no fixed dimensionality yet."""
        self._items: dict[UUID, VectorRecord] = {}
        self._dimensions: int | None = None
        self.closed = False

    async def upsert(self, record: VectorRecord) -> None:
        """Store `record`, fixing this store's dimensionality on the first call."""
        if self._dimensions is None:
            self._dimensions = record.dimensions
        require_matching_dimensions([record], dimensions=self._dimensions)
        self._items[record.id] = record

    async def get(self, record_id: UUID) -> VectorRecord | None:
        """Retrieve a record by id, or None if not present."""
        return self._items.get(record_id)

    async def delete(self, record_id: UUID) -> None:
        """Remove a record by id, if present."""
        self._items.pop(record_id, None)

    async def exists(self, record_id: UUID) -> bool:
        """Report whether a record with this id is currently stored."""
        return record_id in self._items

    async def search(self, request: SimilaritySearchRequest) -> SimilaritySearchResult:
        """Return every stored record as an exact-match cosine-similarity search.

        A deliberately simple reference implementation: brute-force cosine similarity, exact
        metadata filtering, sorted and truncated per the `VectorStore.search` contract.
        """
        if self._dimensions is not None and request.dimensions != self._dimensions:
            raise VectorDimensionMismatchError(
                f"query dimensionality {request.dimensions} does not match "
                f"store dimensionality {self._dimensions}"
            )

        def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(y * y for y in b))
            if norm_a == 0.0 or norm_b == 0.0:
                return 0.0
            # Clamp for floating-point safety: cosine similarity is mathematically in
            # [-1.0, 1.0], but this rescales to [0.0, 1.0] to satisfy SimilaritySearchMatch.
            return max(0.0, min(1.0, (dot / (norm_a * norm_b) + 1.0) / 2.0))

        candidates = [
            record
            for record in self._items.values()
            if all(record.metadata.get(key) == value for key, value in request.metadata_filter.items())
        ]
        matches = tuple(
            sorted(
                (
                    SimilaritySearchMatch(
                        record=record, score=_cosine(request.query_embedding, record.embedding)
                    )
                    for record in candidates
                ),
                key=lambda match: (-match.score, str(match.record.id)),
            )
        )
        return SimilaritySearchResult(matches=matches[: request.limit])

    async def aclose(self) -> None:
        """Mark this store as closed."""
        self.closed = True


@pytest.mark.asyncio
async def test_in_memory_vector_store_round_trip() -> None:
    """A concrete `VectorStore` should support the full upsert/get/exists/delete contract."""
    store = _InMemoryVectorStore()
    record = _record()

    assert await store.exists(record.id) is False
    await store.upsert(record)
    assert await store.get(record.id) == record
    assert await store.exists(record.id) is True

    await store.delete(record.id)
    assert await store.get(record.id) is None
    assert await store.exists(record.id) is False


@pytest.mark.asyncio
async def test_in_memory_vector_store_delete_is_a_no_op_for_a_missing_record() -> None:
    """Deleting a `record_id` with no matching record should not raise."""
    store = _InMemoryVectorStore()
    await store.delete(RECORD_A)


@pytest.mark.asyncio
async def test_in_memory_vector_store_upsert_overwrites_same_id() -> None:
    """Upserting a record sharing an existing `id` should overwrite it."""
    store = _InMemoryVectorStore()
    await store.upsert(_record(embedding=(1.0, 0.0)))
    await store.upsert(_record(embedding=(0.0, 1.0)))
    stored = await store.get(RECORD_A)
    assert stored is not None
    assert stored.embedding == (0.0, 1.0)


@pytest.mark.asyncio
async def test_in_memory_vector_store_upsert_rejects_mismatched_dimensions() -> None:
    """Upserting a record whose dimensionality differs from the store's should raise."""
    store = _InMemoryVectorStore()
    await store.upsert(_record(RECORD_A, embedding=(1.0, 0.0)))
    with pytest.raises(VectorDimensionMismatchError):
        await store.upsert(_record(RECORD_B, embedding=(1.0, 0.0, 0.0)))


@pytest.mark.asyncio
async def test_in_memory_vector_store_search_orders_by_similarity_descending() -> None:
    """`search` should return matches ordered from most to least similar."""
    store = _InMemoryVectorStore()
    await store.upsert(_record(RECORD_A, embedding=(1.0, 0.0)))
    await store.upsert(_record(RECORD_B, embedding=(0.0, 1.0)))
    await store.upsert(_record(RECORD_C, embedding=(0.9, 0.1)))

    result = await store.search(SimilaritySearchRequest(query_embedding=(1.0, 0.0)))

    assert [match.record.id for match in result.matches] == [RECORD_A, RECORD_C, RECORD_B]


@pytest.mark.asyncio
async def test_in_memory_vector_store_search_respects_limit() -> None:
    """`search` should return at most `request.limit` matches."""
    store = _InMemoryVectorStore()
    await store.upsert(_record(RECORD_A, embedding=(1.0, 0.0)))
    await store.upsert(_record(RECORD_B, embedding=(0.9, 0.1)))
    await store.upsert(_record(RECORD_C, embedding=(0.8, 0.2)))

    result = await store.search(SimilaritySearchRequest(query_embedding=(1.0, 0.0), limit=2))

    assert result.match_count == 2


@pytest.mark.asyncio
async def test_in_memory_vector_store_search_applies_metadata_filter() -> None:
    """`search` should only return records matching every `metadata_filter` entry."""
    store = _InMemoryVectorStore()
    await store.upsert(
        VectorRecord(id=RECORD_A, entity_id=ENTITY_A, embedding=(1.0, 0.0), metadata={"lang": "py"})
    )
    await store.upsert(
        VectorRecord(id=RECORD_B, entity_id=ENTITY_A, embedding=(1.0, 0.0), metadata={"lang": "go"})
    )

    result = await store.search(
        SimilaritySearchRequest(query_embedding=(1.0, 0.0), metadata_filter={"lang": "py"})
    )

    assert [match.record.id for match in result.matches] == [RECORD_A]


@pytest.mark.asyncio
async def test_in_memory_vector_store_search_rejects_mismatched_query_dimensions() -> None:
    """A query embedding of the wrong dimensionality should raise."""
    store = _InMemoryVectorStore()
    await store.upsert(_record(embedding=(1.0, 0.0)))
    with pytest.raises(VectorDimensionMismatchError):
        await store.search(SimilaritySearchRequest(query_embedding=(1.0, 0.0, 0.0)))


@pytest.mark.asyncio
async def test_in_memory_vector_store_aclose_releases_the_store() -> None:
    """`aclose` should run without raising and reflect the store's closed state."""
    store = _InMemoryVectorStore()
    assert store.closed is False
    await store.aclose()
    assert store.closed is True


def test_in_memory_vector_store_satisfies_supports_async_close() -> None:
    """A fully-implemented `VectorStore` should structurally satisfy `SupportsAsyncClose`,
    proving `aclose` integrates with `core.protocols` without formally inheriting from it."""
    assert isinstance(_InMemoryVectorStore(), SupportsAsyncClose)
