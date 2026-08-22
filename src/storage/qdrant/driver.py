"""Concrete Qdrant-backed implementation of `vector.base.VectorStore`.

Requires the `qdrant-client` package. **Not yet a declared dependency of this project -- see
the dependency note in `docs/phase10_summary.md` for exactly what to add to `pyproject.toml`;
`pyproject.toml` itself was deliberately left untouched, per this phase's own "STOP before
modifying pyproject.toml" instruction.** This module imports `qdrant_client` directly (a genuine
driver against the real client, not a further abstraction over it), so it cannot be imported in
an environment that has not separately installed it.

A client is always supplied by the caller -- an already-constructed
`qdrant_client.AsyncQdrantClient`, pointed at whatever server and configured with whatever auth
the caller needs -- injected into `QdrantVectorStore.__init__` alongside an explicit
`collection_name` and `vector_size`; this driver never constructs its own client, never
hardcodes a server address, and never hardcodes a collection name. Collection creation is an
explicit, separate `ensure_collection` step, never a hidden side effect of `__init__` -- matching
this phase's original Qdrant-specific "no hidden network calls during object construction"
requirement.

Deterministic `VectorRecord` <-> Qdrant point mapping: a point's own id is `str(record.id)`
(Qdrant natively accepts UUID-formatted strings as point ids); its payload is `record.metadata`
plus one reserved `"entity_id"` key holding `str(record.entity_id)`; its vector is
`list(record.embedding)`. Reversing this mapping on `get`/`search` reconstructs the exact
original `VectorRecord` -- provided no caller-supplied metadata key collides with the reserved
`"entity_id"` key; this driver does not itself guard against that collision, since
`vector.base.VectorRecord.metadata` is caller-controlled freeform data this driver has no basis
to restrict.

This driver enforces a single, fixed embedding dimensionality (`vector_size`, given at
construction) via `vector.base.require_matching_dimensions` on `upsert` and an equivalent
explicit check on `search`, and always configures the collection for Cosine distance --
`VectorStore.search`'s own contract requires similarity scores normalized to `[0.0, 1.0]`, and
Qdrant's raw Cosine-distance score is a cosine similarity in `[-1.0, 1.0]`; this driver linearly
rescales it via `(raw + 1.0) / 2.0`, clamped to `[0.0, 1.0]` defensively against floating-point
overshoot at the boundaries.

`SimilaritySearchRequest.metadata_filter` values are passed to Qdrant's `MatchValue`, which
accepts only `bool`, `int`, or `str` -- a metadata filter value of any other type raises a
`QdrantOperationError` wrapping the client's own rejection, rather than this driver silently
coercing it.
"""

from typing import Any, Protocol
from uuid import UUID

from qdrant_client.http import models

from src.core.exceptions import ValidationError, VAOSError
from src.core.logging import get_logger
from src.vector.base import (
    SimilaritySearchMatch,
    SimilaritySearchRequest,
    SimilaritySearchResult,
    VectorDimensionMismatchError,
    VectorRecord,
    VectorStore,
    require_matching_dimensions,
)

_logger = get_logger("storage.qdrant")

_ENTITY_ID_KEY = "entity_id"


class _QdrantClientLike(Protocol):
    """Structural shape of the subset of `qdrant_client.AsyncQdrantClient`'s calling convention
    this driver uses.

    `AsyncQdrantClient` itself satisfies this Protocol, so a real client can always be injected;
    typing against this Protocol rather than the concrete class also lets a test double stand in
    without subclassing `AsyncQdrantClient`, matching `storage.postgres`'s own
    `_AsyncpgConnectionLike` precedent for the same reason.
    """

    async def collection_exists(self, collection_name: str, **kwargs: Any) -> bool:
        """Report whether `collection_name` currently exists."""
        ...

    async def create_collection(
        self, collection_name: str, vectors_config: Any, **kwargs: Any
    ) -> bool:
        """Create a new collection."""
        ...

    async def upsert(
        self, collection_name: str, points: list[models.PointStruct], **kwargs: Any
    ) -> Any:
        """Insert or overwrite one or more points."""
        ...

    async def retrieve(
        self,
        collection_name: str,
        ids: list[str],
        with_payload: bool = True,
        with_vectors: bool = False,
        **kwargs: Any,
    ) -> list[Any]:
        """Retrieve points by id."""
        ...

    async def delete(
        self, collection_name: str, points_selector: list[str], **kwargs: Any
    ) -> Any:
        """Delete points by id."""
        ...

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
        """Find the points most similar to `query_vector`."""
        ...

    async def close(self, **kwargs: Any) -> None:
        """Release this client's own resources."""
        ...


class QdrantOperationError(VAOSError):
    """Raised when an operation against the underlying Qdrant client fails.

    Wraps whatever exception `qdrant_client` itself raises -- its exception hierarchy is not
    consistently one common base across transport modes (REST vs. gRPC), so this catches broadly
    and re-raises as a single, VAOS-compatible type, matching
    `repository.git.GitCommandError`'s own role of wrapping an external tool's failures.
    """


class QdrantVectorStore(VectorStore):
    """A `VectorStore` backed by an injected `qdrant_client.AsyncQdrantClient`."""

    def __init__(
        self, client: _QdrantClientLike, *, collection_name: str, vector_size: int
    ) -> None:
        """Initialize the store. Performs no network call itself.

        Args:
            client: An already-constructed `AsyncQdrantClient` (or anything satisfying the same
                `collection_exists`/`create_collection`/`upsert`/`retrieve`/`delete`/`search`/
                `close` calling convention). This driver never constructs its own client or
                hardcodes a server address; the caller owns the client's own connection
                lifecycle.
            collection_name: Name of the Qdrant collection this store reads and writes -- never
                hardcoded; the caller decides.
            vector_size: Fixed embedding dimensionality this store enforces on every `upsert`
                and `search`, and the dimensionality `ensure_collection` creates the collection
                with.

        Raises:
            ValidationError: If `collection_name` is blank or `vector_size` is not positive.
        """
        if not collection_name.strip():
            raise ValidationError("QdrantVectorStore: collection_name must not be empty")
        if vector_size <= 0:
            raise ValidationError(
                "QdrantVectorStore: vector_size must be positive",
                details={"vector_size": vector_size},
            )
        self._client = client
        self._collection_name = collection_name
        self._vector_size = vector_size

    async def ensure_collection(self) -> None:
        """Create this store's collection, configured for Cosine distance, if it does not exist.

        Idempotent: safe to call against a collection that already exists. Never called
        implicitly by `__init__` -- an explicit, separate step (see module docstring).

        Raises:
            QdrantOperationError: If checking for or creating the collection fails.
        """
        try:
            exists = await self._client.collection_exists(self._collection_name)
            if not exists:
                await self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=models.VectorParams(
                        size=self._vector_size, distance=models.Distance.COSINE
                    ),
                )
        except Exception as exc:
            raise QdrantOperationError(
                f"could not ensure collection '{self._collection_name}': {exc}",
                details={"collection_name": self._collection_name},
            ) from exc

    async def upsert(self, record: VectorRecord) -> None:
        """Insert `record`, or overwrite the existing record sharing its `id`.

        Args:
            record: The vector record to store.

        Raises:
            VectorDimensionMismatchError: If `record.dimensions` does not equal this store's
                `vector_size`.
            QdrantOperationError: If the upsert fails for any other reason.
        """
        require_matching_dimensions([record], dimensions=self._vector_size)
        point = models.PointStruct(
            id=str(record.id),
            vector=list(record.embedding),
            payload={_ENTITY_ID_KEY: str(record.entity_id), **record.metadata},
        )
        try:
            await self._client.upsert(collection_name=self._collection_name, points=[point])
        except Exception as exc:
            raise QdrantOperationError(
                f"could not upsert vector record '{record.id}': {exc}",
                details={"record_id": str(record.id), "collection_name": self._collection_name},
            ) from exc

    async def get(self, record_id: UUID) -> VectorRecord | None:
        """Retrieve a single vector record by its own `id`.

        Args:
            record_id: Identifier of the vector record to retrieve.

        Returns:
            The matching record, or None if no record exists with that id.

        Raises:
            QdrantOperationError: If the retrieval fails, or the stored payload is missing the
                reserved `"entity_id"` key this driver itself always writes.
        """
        try:
            points = await self._client.retrieve(
                collection_name=self._collection_name,
                ids=[str(record_id)],
                with_payload=True,
                with_vectors=True,
            )
        except Exception as exc:
            raise QdrantOperationError(
                f"could not retrieve vector record '{record_id}': {exc}",
                details={"record_id": str(record_id), "collection_name": self._collection_name},
            ) from exc
        if not points:
            return None
        return self._point_to_record(points[0])

    async def delete(self, record_id: UUID) -> None:
        """Remove a vector record by its own `id`; a no-op if it does not exist.

        Args:
            record_id: Identifier of the vector record to remove.

        Raises:
            QdrantOperationError: If the delete fails.
        """
        try:
            await self._client.delete(
                collection_name=self._collection_name, points_selector=[str(record_id)]
            )
        except Exception as exc:
            raise QdrantOperationError(
                f"could not delete vector record '{record_id}': {exc}",
                details={"record_id": str(record_id), "collection_name": self._collection_name},
            ) from exc

    async def exists(self, record_id: UUID) -> bool:
        """Report whether a vector record with `record_id` is currently stored.

        Args:
            record_id: Identifier to check.

        Returns:
            True if a matching record is currently stored.

        Raises:
            QdrantOperationError: If the check fails.
        """
        try:
            points = await self._client.retrieve(
                collection_name=self._collection_name,
                ids=[str(record_id)],
                with_payload=False,
                with_vectors=False,
            )
        except Exception as exc:
            raise QdrantOperationError(
                f"could not check existence of vector record '{record_id}': {exc}",
                details={"record_id": str(record_id), "collection_name": self._collection_name},
            ) from exc
        return len(points) > 0

    async def search(self, request: SimilaritySearchRequest) -> SimilaritySearchResult:
        """Find the vector records most similar to `request.query_embedding`.

        Args:
            request: The similarity-search query.

        Returns:
            A `SimilaritySearchResult` with at most `request.limit` matches, ordered per
            `SimilaritySearchResult.__post_init__`, with each match's `score` rescaled from raw
            Cosine similarity into `[0.0, 1.0]` (see module docstring).

        Raises:
            VectorDimensionMismatchError: If `request.dimensions` does not equal this store's
                `vector_size`.
            QdrantOperationError: If the search fails.
        """
        if request.dimensions != self._vector_size:
            raise VectorDimensionMismatchError(
                f"SimilaritySearchRequest dimensionality {request.dimensions} does not match "
                f"expected {self._vector_size}",
                details={
                    "expected_dimensions": self._vector_size,
                    "actual_dimensions": request.dimensions,
                },
            )
        query_filter = self._build_filter(request.metadata_filter)
        try:
            scored_points = await self._client.search(
                collection_name=self._collection_name,
                query_vector=list(request.query_embedding),
                query_filter=query_filter,
                limit=request.limit,
                with_payload=True,
                with_vectors=True,
            )
        except Exception as exc:
            raise QdrantOperationError(
                f"could not search collection '{self._collection_name}': {exc}",
                details={"collection_name": self._collection_name},
            ) from exc
        matches = tuple(
            sorted(
                (self._scored_point_to_match(point) for point in scored_points),
                key=lambda match: (-match.score, str(match.record.id)),
            )
        )
        return SimilaritySearchResult(matches=matches)

    async def aclose(self) -> None:
        """Release the underlying client's resources."""
        await self._client.close()

    def _point_to_record(self, point: Any) -> VectorRecord:
        """Reconstruct a `VectorRecord` from a Qdrant `Record` or `ScoredPoint`.

        Args:
            point: A `qdrant_client` `Record`/`ScoredPoint`, with `id`, `payload`, and `vector`
                populated (i.e. retrieved with `with_payload=True, with_vectors=True`).

        Returns:
            The reconstructed `VectorRecord`.

        Raises:
            QdrantOperationError: If `point.payload` is missing the reserved `"entity_id"` key,
                or `point.vector` is missing -- both always written by `upsert`, so their
                absence indicates the point was not written by this driver.
        """
        payload = dict(point.payload or {})
        if _ENTITY_ID_KEY not in payload:
            raise QdrantOperationError(
                f"vector record '{point.id}' is missing the reserved '{_ENTITY_ID_KEY}' "
                "payload key -- it was not written by this driver",
                details={"record_id": str(point.id)},
            )
        entity_id = payload.pop(_ENTITY_ID_KEY)
        vector = point.vector
        if vector is None:
            raise QdrantOperationError(
                f"vector record '{point.id}' was retrieved without its embedding",
                details={"record_id": str(point.id)},
            )
        embedding = tuple(vector) if not isinstance(vector, dict) else tuple(next(iter(vector.values())))
        return VectorRecord(
            id=UUID(str(point.id)),
            entity_id=UUID(str(entity_id)),
            embedding=embedding,
            metadata=payload,
        )

    def _scored_point_to_match(self, point: Any) -> SimilaritySearchMatch:
        """Convert a Qdrant `ScoredPoint` into a `SimilaritySearchMatch`.

        Args:
            point: The scored point returned by `search`.

        Returns:
            The corresponding match, with `score` rescaled from Cosine similarity `[-1.0, 1.0]`
            into the `[0.0, 1.0]` range `SimilaritySearchMatch` requires (see module docstring).
        """
        record = self._point_to_record(point)
        normalized_score = max(0.0, min(1.0, (point.score + 1.0) / 2.0))
        return SimilaritySearchMatch(record=record, score=normalized_score)

    def _build_filter(self, metadata_filter: dict[str, Any]) -> models.Filter | None:
        """Convert a `SimilaritySearchRequest.metadata_filter` into a Qdrant `Filter`.

        Args:
            metadata_filter: Exact-match metadata constraints; empty means no filtering.

        Returns:
            A `Filter` requiring every key/value pair (via `must`), or None if `metadata_filter`
            is empty.
        """
        if not metadata_filter:
            return None
        return models.Filter(
            must=[
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in metadata_filter.items()
            ]
        )
