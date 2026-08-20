"""Vector layer: the domain-level contract for embeddings and similarity search.

`vector` is an infrastructure-adjacent layer that may depend on `core` and
`domain`, but not on any other VAOS layer -- in particular, not on
`storage`. It defines the abstract `VectorStore` Port and its supporting
value objects (`VectorRecord`, `SimilaritySearchRequest`,
`SimilaritySearchMatch`, `SimilaritySearchResult`) in `base.py`.

This package answers "what does it mean to persist an embedding and search
for the ones most similar to a query" -- it does not implement a vector
database, does not add a Qdrant (or any other) client dependency, and does
not decide how a concrete store is wired up at runtime. Storage drivers,
including the future Qdrant driver, depend on `vector`; `vector` never
depends on them. That inversion is deliberate: `storage` (Phase 10) left
its own vector backend intentionally unimplemented pending this contract,
and any future concrete `VectorStore` implementation -- whether it lives
under `storage` or a dedicated `vector` driver package -- is expected to
implement the Port defined here rather than this package reaching for a
concrete store itself.

`base.py` is self-contained and imported directly by its full path (e.g.
`from src.vector.base import VectorStore`); this package intentionally
does not re-export a combined surface from `__init__.py`.
"""
