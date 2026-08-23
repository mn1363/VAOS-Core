"""Memory Port: the domain-level contract for persistent, structured project knowledge.

`MemoryStore` is the abstraction this phase exists to define: a single, backend-agnostic contract
for storing and deterministically retrieving structured project knowledge, independent of which
concrete backend (filesystem, SQLite, PostgreSQL, or any other) eventually implements it. This
module defines exactly that contract -- `MemoryRecord` (a single piece of stored knowledge,
optionally tied to a domain entity by id), the query/result shapes (`MemoryQuery`,
`MemoryQueryResult`), and the abstract `MemoryStore` Port itself -- and nothing more. It does not
implement a database, file store, or cache, does not add any external dependency, and does not
decide how a concrete store is wired up at runtime; those are a future storage driver's concerns,
built against this Port via Dependency Inversion, the same relationship `vector.base.VectorStore`
has to its own not-yet-built concrete backends.

Every `MemoryRecord` carries an optional `entity_id: UUID | None` tying it back to an existing
`domain.entities.Entity.id` (e.g. a `SourceRepository.id` or `AnalysisRun.id`), when the knowledge
is about one entity in particular -- reusing that field's own name and type rather than importing
the entity class itself, matching `vector.base.VectorRecord.entity_id`'s own precedent for this
exact allowed-but-unused relationship to `src.domain`. Unlike `VectorRecord.entity_id`, which is
mandatory (every embedding represents some entity), `MemoryRecord.entity_id` is optional: a piece
of project knowledge may be about the project as a whole rather than about any single collected
entity, and forcing an artificial association would misrepresent it.

`MemoryRecord` is a new, freestanding value object -- a frozen, slotted dataclass, not a
`domain.entities.Entity` subclass. It is deliberately immutable and lifecycle-free, matching
`vector.base.VectorRecord`'s own precedent exactly (and for the same reason): every `Entity`
subclass is mutable, with its own `touch()`-driven `updated_at` and, where relevant, explicit
state-transition methods enforcing a status machine (see `domain.entities.SourceRepository.
mark_ready`, `AnalysisRun.complete`). Nothing in this phase's own contract calls for a comparable
status machine -- a `MemoryRecord` is either stored or it is not, and `MemoryStore.upsert`/`delete`
already express that fully -- so no `status` field or state-transition method was added
speculatively. This phase's own "explicit lifecycle behavior where required" is satisfied by
`MemoryStore`'s own Port methods (`upsert`, `get`, `delete`, `exists`, `query`, `aclose`), which
together define a record's entire observable lifecycle in the store, rather than by a second,
duplicate lifecycle encoded on `MemoryRecord` itself.

`MemoryRecord` does carry `created_at`/`updated_at` timestamps -- reusing `domain.entities.
Entity`'s own two field names and types, and the same `datetime.now(UTC)` default-factory
convention, without importing `Entity` itself. A monotonic version counter (the brief's other
named option, "version information") was not added alongside or instead of them: nothing in the
existing frozen architecture reads or enforces one (there is no optimistic-concurrency requirement
anywhere upstream of this phase), so adding one would be speculative. A caller that upserts a
changed record is expected to pass a new `updated_at`; `MemoryStore.upsert` itself does not
mutate timestamps on a caller's behalf, keeping the Port's behavior fully determined by its input.

Every `MemoryStore` method is async, matching `domain.interfaces.Repository`'s and `vector.base.
VectorStore`'s own async persistence Ports, since a concrete implementation is expected to perform
I/O.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.core.exceptions import ValidationError
from src.core.logging import get_logger

_logger = get_logger("memory")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A single piece of persistent, structured project knowledge.

    Attributes:
        id: Stable identifier of this memory record itself, distinct from `entity_id` so a
            single entity may in principle be represented by more than one memory record, each
            with its own independent lifecycle.
        memory_type: Freeform label for the kind of knowledge this record holds (e.g.
            `"architecture_decision"`, `"reuse_candidate_note"`). Deliberately a plain string
            rather than a fixed enum -- the exact taxonomy belongs to whichever future layer
            produces or consumes memory records, not to this Port -- matching `domain.entities.
            Finding.category`'s own precedent and justification exactly.
        content: The structured knowledge payload itself, as a JSON-safe mapping. Distinct from
            `metadata`: `content` is the knowledge being remembered; `metadata` is freeform,
            descriptive context about that knowledge (e.g. its confidence, its author).
        metadata: Freeform, structured metadata carried alongside `content`, usable as filtering
            criteria by `MemoryQuery.metadata_filter`.
        entity_id: Identifier of the domain entity/document this record is about, matching an
            existing `domain.entities.Entity.id` value (e.g. a `SourceRepository.id`), if the
            knowledge concerns one entity in particular. None when the knowledge is about the
            project as a whole rather than any single entity.
        created_at: Timestamp at which this record was first stored.
        updated_at: Timestamp at which this record was last stored via `MemoryStore.upsert`.
    """

    id: UUID
    memory_type: str
    content: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    entity_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate construction-time invariants.

        Raises:
            ValidationError: If `memory_type` is blank.
        """
        if not self.memory_type.strip():
            raise ValidationError(
                "MemoryRecord: memory_type must not be empty", details={"record_id": str(self.id)}
            )


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """A single deterministic filter request against a `MemoryStore`.

    Every constraint is optional and constraints combine with logical AND; a default,
    fully-unconstrained `MemoryQuery()` requests every stored record, up to `limit`. This is a
    deterministic, exact-match filter -- not a similarity search. Semantic/vector search over
    memory content is explicitly out of scope for this Port; see `vector.base.
    SimilaritySearchRequest` for that concern.

    Attributes:
        memory_type: If given, only records with exactly this `MemoryRecord.memory_type` match.
        entity_id: If given, only records with exactly this `MemoryRecord.entity_id` match.
        metadata_filter: Exact-match metadata constraints a candidate `MemoryRecord.metadata`
            must satisfy to be eligible -- every key/value pair here must be present, with an
            equal value, in a candidate's own metadata. Empty means no metadata filtering.
        limit: Maximum number of records to return. Must be positive.
    """

    memory_type: str | None = None
    entity_id: UUID | None = None
    metadata_filter: dict[str, Any] = field(default_factory=dict)
    limit: int = 100

    def __post_init__(self) -> None:
        """Validate query invariants.

        Raises:
            ValidationError: If `memory_type` is given but blank, or if `limit` is not positive.
        """
        if self.memory_type is not None and not self.memory_type.strip():
            raise ValidationError("MemoryQuery: memory_type must not be empty when given")
        if self.limit <= 0:
            raise ValidationError(
                "MemoryQuery: limit must be positive", details={"limit": self.limit}
            )


@dataclass(frozen=True, slots=True)
class MemoryQueryResult:
    """A deterministically ordered set of `MemoryRecord`s matching one `MemoryQuery`.

    Attributes:
        records: Every matching record, sorted by ascending `id` -- so the result is
            deterministic regardless of the concrete store's own internal ordering, mirroring
            `vector.base.SimilaritySearchResult`'s own role for its Port. Unlike
            `SimilaritySearchResult`, ordering is by `id` alone rather than by a relevance score:
            this Port performs no scoring (see `MemoryQuery`'s own docstring), so no score exists
            to order by.
    """

    records: tuple[MemoryRecord, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `records` is sorted by `id` and free of duplicates.

        Raises:
            ValidationError: If `records` is not sorted by ascending `id`, or contains two
                entries with the same `id`.
        """
        sort_keys = [str(record.id) for record in self.records]
        if sort_keys != sorted(sort_keys):
            raise ValidationError("MemoryQueryResult: records must be sorted by ascending id")
        if len(set(sort_keys)) != len(sort_keys):
            raise ValidationError("MemoryQueryResult: records must not contain duplicate ids")

    @property
    def record_count(self) -> int:
        """Total number of records in this result."""
        return len(self.records)

    def top(self, count: int) -> tuple[MemoryRecord, ...]:
        """Retrieve the first `count` records.

        Args:
            count: How many records to return. Values greater than `record_count` return every
                record.

        Returns:
            The first `count` entries of `records`, in existing order.

        Raises:
            ValidationError: If `count` is negative.
        """
        if count < 0:
            raise ValidationError("MemoryQueryResult.top: count must not be negative")
        return self.records[:count]


class MemoryStore(ABC):
    """Abstract persistence and query Port for `MemoryRecord`s.

    A concrete implementation -- a future `storage`/`memory` driver -- owns the actual backing
    store and any network, database, or file resources it needs; this Port defines only the
    contract every such driver must satisfy. It does not itself perform I/O or hold a connection.
    """

    @abstractmethod
    async def upsert(self, record: MemoryRecord) -> None:
        """Insert `record`, or overwrite the existing record sharing its `id`.

        Args:
            record: The memory record to store.
        """
        ...

    @abstractmethod
    async def get(self, record_id: UUID) -> MemoryRecord | None:
        """Retrieve a single memory record by its own `id`.

        Args:
            record_id: Identifier of the memory record to retrieve.

        Returns:
            The matching record, or None if no record exists with that id.
        """
        ...

    @abstractmethod
    async def delete(self, record_id: UUID) -> None:
        """Remove a memory record by its own `id`.

        Args:
            record_id: Identifier of the memory record to remove.

        A `record_id` with no matching record is not an error; this is a no-op in that case,
        matching `vector.base.VectorStore.delete`'s own precedent.
        """
        ...

    @abstractmethod
    async def exists(self, record_id: UUID) -> bool:
        """Report whether a memory record with `record_id` is currently stored.

        Args:
            record_id: Identifier to check.

        Returns:
            True if a matching record is currently stored.
        """
        ...

    @abstractmethod
    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        """Find every stored memory record matching `request`.

        Args:
            request: The filter query, including its own result `limit`.

        Returns:
            A `MemoryQueryResult` with at most `request.limit` records, ordered per
            `MemoryQueryResult.__post_init__`.
        """
        ...

    @abstractmethod
    async def aclose(self) -> None:
        """Release any resources this store holds (connections, file handles, ...).

        Matches `core.protocols.SupportsAsyncClose`'s shape, so any registered store can be
        closed uniformly regardless of which concrete driver backs it.
        """
        ...


def matches_query(record: MemoryRecord, query: MemoryQuery) -> bool:
    """Report whether `record` satisfies every constraint in `query`.

    A concrete `MemoryStore` calls this once per candidate record when evaluating `query`, so a
    query's exact-match semantics are defined identically across every implementation, mirroring
    `foundation.ranking.base.require_unique_subjects`'s own role of giving every implementation a
    single, shared definition of correct behavior to call rather than re-derive.

    Args:
        record: The candidate record to test.
        query: The query to test it against.

    Returns:
        True if `record` satisfies every constraint `query` specifies (`memory_type`, `entity_id`,
        and every `metadata_filter` entry); constraints left unset in `query` are not checked.
    """
    if query.memory_type is not None and record.memory_type != query.memory_type:
        return False
    if query.entity_id is not None and record.entity_id != query.entity_id:
        return False
    for key, value in query.metadata_filter.items():
        if record.metadata.get(key) != value:
            return False
    return True
