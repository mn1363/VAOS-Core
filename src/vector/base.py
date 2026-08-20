"""Vector Port: the domain-level contract for embedding persistence and similarity search.

`VectorStore` is the abstraction intentionally deferred from Phase 10 (`storage`): a store's
Qdrant backend was left unimplemented because no frozen contract for "what is a vector, and
what does it mean to persist and search for one" yet existed. This module defines exactly that
contract -- `VectorRecord` (a single embedding, tied to a domain entity by id), the similarity-
search request/match/result shapes, and the abstract `VectorStore` Port itself -- and nothing
more. It does not implement a vector database, does not add a Qdrant (or any other) client
dependency, and does not decide how a concrete store is wired up at runtime; those are a future
storage driver's concerns, built against this Port via Dependency Inversion, the same relationship
`repository.base.RepositoryClient` has to `repository.git.GitRepositoryClient`.

Every `VectorRecord` carries an `entity_id: UUID` tying it back to an existing
`domain.entities.Entity.id` (e.g. a `SourceFile.id`) -- reusing that field's own name and type
rather than importing the entity class itself, matching `foundation.comparer.base.
FoundationSubject.repository_id`'s own precedent for this exact allowed-but-unused relationship
to `src.domain`. A `VectorRecord`'s own `id` is a separate, vector-record-scoped identifier, so a
single entity may in principle be represented by more than one vector record (e.g. one per chunk
of a large file), each upserted, retrieved, and deleted independently.

Every `VectorStore` method is async, matching `domain.interfaces.Repository`'s own async
persistence Port, since a concrete implementation is expected to perform I/O.
"""

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.core.exceptions import ValidationError
from src.core.logging import get_logger

_logger = get_logger("vector")


class VectorDimensionMismatchError(ValidationError):
    """Raised when an embedding's dimensionality does not match what a store expects.

    A concrete `VectorStore` that enforces a single, fixed embedding dimensionality across its
    whole collection raises this -- rather than a bare `ValidationError` -- so a caller can
    catch dimension mismatches specifically, without also catching every other kind of
    validation failure.

    Attributes:
        message: Human-readable description of what went wrong.
        details: Structured context about the failure, typically including the record or query
            embedding's actual dimensionality and the dimensionality that was expected.
    """


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """A single embedding persisted against an associated domain entity.

    Attributes:
        id: Stable identifier of this vector record itself, distinct from `entity_id` so the
            same entity may be represented by more than one vector record, each with its own
            independent lifecycle.
        entity_id: Identifier of the domain entity/document this vector represents, matching an
            existing `domain.entities.Entity.id` value (e.g. a `SourceFile.id`).
        embedding: The embedding itself, as an ordered, immutable sequence of finite floats.
            Must be non-empty.
        metadata: Freeform, structured metadata carried alongside the embedding (e.g. a chunk
            index, a source `relative_path`), usable as filtering criteria by
            `SimilaritySearchRequest.metadata_filter`.
    """

    id: UUID
    entity_id: UUID
    embedding: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate embedding invariants.

        Raises:
            ValidationError: If `embedding` is empty, or contains a non-finite (NaN or
                infinite) value.
        """
        if not self.embedding:
            raise ValidationError(
                "VectorRecord: embedding must not be empty", details={"record_id": str(self.id)}
            )
        if not all(math.isfinite(component) for component in self.embedding):
            raise ValidationError(
                "VectorRecord: embedding must contain only finite values",
                details={"record_id": str(self.id)},
            )

    @property
    def dimensions(self) -> int:
        """Dimensionality of `embedding`."""
        return len(self.embedding)


@dataclass(frozen=True, slots=True)
class SimilaritySearchRequest:
    """A single similarity-search query against a `VectorStore`.

    Attributes:
        query_embedding: The embedding to search for nearest neighbors of.
        limit: Maximum number of results to return. Must be positive.
        metadata_filter: Optional exact-match metadata constraints a candidate
            `VectorRecord.metadata` must satisfy to be eligible -- every key/value pair here must
            be present, with an equal value, in a candidate's own metadata. Empty means no
            filtering.
    """

    query_embedding: tuple[float, ...]
    limit: int = 10
    metadata_filter: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate query invariants.

        Raises:
            ValidationError: If `query_embedding` is empty or contains a non-finite value, or if
                `limit` is not positive.
        """
        if not self.query_embedding:
            raise ValidationError("SimilaritySearchRequest: query_embedding must not be empty")
        if not all(math.isfinite(component) for component in self.query_embedding):
            raise ValidationError(
                "SimilaritySearchRequest: query_embedding must contain only finite values"
            )
        if self.limit <= 0:
            raise ValidationError(
                "SimilaritySearchRequest: limit must be positive", details={"limit": self.limit}
            )

    @property
    def dimensions(self) -> int:
        """Dimensionality of `query_embedding`."""
        return len(self.query_embedding)


@dataclass(frozen=True, slots=True)
class SimilaritySearchMatch:
    """A single scored result from a similarity search.

    Attributes:
        record: The matched `VectorRecord`.
        score: Similarity score for this match, normalized to `[0.0, 1.0]` -- higher means more
            similar. The exact similarity metric (cosine, dot product, ...) is a concrete
            `VectorStore`'s own decision; only the normalized range and "higher is more similar"
            direction are fixed here, so matches from different concrete stores stay comparable.
    """

    record: VectorRecord
    score: float

    def __post_init__(self) -> None:
        """Validate that `score` is within range.

        Raises:
            ValidationError: If `score` falls outside `[0.0, 1.0]`.
        """
        if not 0.0 <= self.score <= 1.0:
            raise ValidationError(
                "SimilaritySearchMatch: score must be between 0.0 and 1.0",
                details={"record_id": str(self.record.id), "score": self.score},
            )


@dataclass(frozen=True, slots=True)
class SimilaritySearchResult:
    """A deterministically ordered set of `SimilaritySearchMatch`es for one search.

    Attributes:
        matches: Every match found, sorted by `(-score, record.id)` -- highest similarity first,
            ties broken by ascending record id -- so the result is deterministic regardless of
            the concrete store's own internal ordering, mirroring `foundation.ranking.base.
            FoundationRanking.scores`'s own `(-value, subject_id)` convention.
    """

    matches: tuple[SimilaritySearchMatch, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `matches` is sorted by `(-score, record.id)` and free of duplicates.

        Raises:
            ValidationError: If `matches` is not in `(-score, record.id)` order, or contains two
                entries for the same `record.id`.
        """
        sort_keys = [(-match.score, str(match.record.id)) for match in self.matches]
        if sort_keys != sorted(sort_keys):
            raise ValidationError(
                "SimilaritySearchResult: matches must be sorted by (-score, record.id)"
            )
        record_ids = [match.record.id for match in self.matches]
        if len(set(record_ids)) != len(record_ids):
            raise ValidationError(
                "SimilaritySearchResult: matches must not contain duplicate records"
            )

    @property
    def match_count(self) -> int:
        """Total number of matches in this result."""
        return len(self.matches)

    def top(self, count: int) -> tuple[SimilaritySearchMatch, ...]:
        """Retrieve the `count` highest-scoring matches.

        Args:
            count: How many matches to return. Values greater than `match_count` return every
                match.

        Returns:
            The first `count` entries of `matches`, in existing order.

        Raises:
            ValidationError: If `count` is negative.
        """
        if count < 0:
            raise ValidationError("SimilaritySearchResult.top: count must not be negative")
        return self.matches[:count]


class VectorStore(ABC):
    """Abstract persistence and similarity-search Port for `VectorRecord`s.

    A concrete implementation -- a future `storage`/`vector` driver, e.g. Qdrant -- owns the
    actual embedding index and any network or on-disk resources it needs; this Port defines only
    the contract every such driver must satisfy. It does not itself perform I/O, hold a
    connection, or enforce a particular embedding dimensionality; a concrete store that does
    enforce one is expected to raise `VectorDimensionMismatchError` from `upsert` and `search`
    when violated, optionally via `require_matching_dimensions` for a batch of records.
    """

    @abstractmethod
    async def upsert(self, record: VectorRecord) -> None:
        """Insert `record`, or overwrite the existing record sharing its `id`.

        Args:
            record: The vector record to store.

        Raises:
            VectorDimensionMismatchError: If this store enforces a fixed embedding
                dimensionality and `record.dimensions` does not match it.
        """
        ...

    @abstractmethod
    async def get(self, record_id: UUID) -> VectorRecord | None:
        """Retrieve a single vector record by its own `id`.

        Args:
            record_id: Identifier of the vector record to retrieve.

        Returns:
            The matching record, or None if no record exists with that id.
        """
        ...

    @abstractmethod
    async def delete(self, record_id: UUID) -> None:
        """Remove a vector record by its own `id`.

        Args:
            record_id: Identifier of the vector record to remove.

        A `record_id` with no matching record is not an error; this is a no-op in that case,
        matching `repository.base.WorkspaceManager.remove`'s own precedent.
        """
        ...

    @abstractmethod
    async def exists(self, record_id: UUID) -> bool:
        """Report whether a vector record with `record_id` is currently stored.

        Args:
            record_id: Identifier to check.

        Returns:
            True if a matching record is currently stored.
        """
        ...

    @abstractmethod
    async def search(self, request: SimilaritySearchRequest) -> SimilaritySearchResult:
        """Find the vector records most similar to `request.query_embedding`.

        Args:
            request: The similarity-search query, including its own result `limit` and optional
                `metadata_filter`.

        Returns:
            A `SimilaritySearchResult` with at most `request.limit` matches, ordered per
            `SimilaritySearchResult.__post_init__`.

        Raises:
            VectorDimensionMismatchError: If this store enforces a fixed embedding
                dimensionality and `request.dimensions` does not match it.
        """
        ...

    @abstractmethod
    async def aclose(self) -> None:
        """Release any resources this store holds (connections, file handles, ...).

        Matches `core.protocols.SupportsAsyncClose`'s shape, so any registered store can be
        closed uniformly regardless of which concrete driver backs it.
        """
        ...


def require_matching_dimensions(
    records: Sequence[VectorRecord], *, dimensions: int
) -> Sequence[VectorRecord]:
    """Validate that every record in `records` has the given embedding `dimensions`.

    A concrete `VectorStore` that enforces a single, fixed embedding dimensionality across its
    whole collection calls this before persisting a batch, so a caller error (an embedding of
    the wrong size) is reported the same way -- as an immediate `VectorDimensionMismatchError`
    -- across every implementation, mirroring `foundation.ranking.base.
    require_unique_subjects`'s own role for its own Port.

    Args:
        records: The vector records to validate.
        dimensions: The fixed embedding dimensionality every record must match.

    Returns:
        `records`, unchanged.

    Raises:
        VectorDimensionMismatchError: If any record's `dimensions` does not equal `dimensions`.
    """
    for record in records:
        if record.dimensions != dimensions:
            _logger.debug(
                "Rejected vector record '%s' with dimensionality %d, expected %d",
                record.id,
                record.dimensions,
                dimensions,
            )
            raise VectorDimensionMismatchError(
                f"VectorRecord dimensionality {record.dimensions} does not match "
                f"expected {dimensions}",
                details={
                    "record_id": str(record.id),
                    "expected_dimensions": dimensions,
                    "actual_dimensions": record.dimensions,
                },
            )
    return records
