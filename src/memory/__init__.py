"""Memory layer: the domain-level contract for persistent, structured project knowledge.

`memory` is an infrastructure-adjacent layer that may depend on `core` and `domain`, but not on
any other VAOS layer -- in particular, not on `storage` or `repository`. It defines the abstract
`MemoryStore` Port and its supporting value objects (`MemoryRecord`, `MemoryQuery`,
`MemoryQueryResult`) in `base.py`.

This package answers "what does it mean to persist a single piece of structured project
knowledge, and to deterministically retrieve the ones matching a given set of criteria" -- it does
not implement a database, file store, or cache, and does not decide how a concrete store is wired
up at runtime. Storage drivers, including a future `memory` driver under `storage`, depend on
`memory`; `memory` never depends on them. That inversion mirrors `vector` (Phase 11)'s own
relationship to `storage` (Phase 10) exactly: `storage` left its Qdrant backend unimplemented
pending Vector's own frozen contract, and any future concrete `MemoryStore` implementation is
expected to implement the Port defined here rather than this package reaching for a concrete store
itself.

`memory` is deliberately narrower than it might first appear. It is NOT a database driver, a
vector database, a graph database, a repository implementation, a cache, or a chatbot conversation
history -- each of those is either an existing layer's own concern (`storage` for backends,
`vector` for embeddings and similarity search, `graph` for relationship topology,
`domain.interfaces.Repository` for entity persistence) or simply out of scope for this phase. It
does not perform semantic or vector search -- `MemoryQuery` is a deterministic, exact-match filter
request, not a similarity query; that distinction, and the Port it belongs to, is `vector`'s alone.
`src.vector` is consequently an allowed dependency for this whole package (per this phase's own
architectural direction) but is deliberately unused: nothing in the existing frozen architecture
requires a `MemoryRecord` to embed or reference a `vector.base.VectorRecord` directly, so no such
reference was added speculatively. `src.domain` is likewise allowed but unused as an import:
`MemoryRecord.entity_id` reuses `domain.entities.Entity.id`'s own field name and type without
importing the entity class itself -- the same allowed-but-unused relationship
`vector.base.VectorRecord.entity_id` already established relative to `src.domain`.

`base.py` is self-contained and imported directly by its full path (e.g. `from src.memory.base
import MemoryStore`); this package intentionally does not re-export a combined surface from
`__init__.py`.
"""
