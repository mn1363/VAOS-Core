"""Storage layer: concrete persistence backends for the Ports `domain` and `vector` define.

`storage` answers two separate questions with one package: *where do domain entities
(`SourceRepository`, `SourceFile`, `AnalysisRun`, `Finding`) actually live once collected and
analyzed?* and *where do embeddings actually live once computed?* It provides concrete adapters
for both -- `domain.interfaces.SourceRepositoryStore`, `SourceFileRepository`,
`AnalysisRunRepository`, `FindingRepository` (Phase 2, left unimplemented pending this phase) via
`filesystem`, `sqlite`, and `postgres` backends, and `vector.base.VectorStore` (Phase 11, left
unimplemented by design pending its own frozen contract) via a `qdrant` backend -- but it defines
no new contract itself: every class here implements an existing, already-frozen Port rather than
introducing one. It does not decide *which* backend a running system uses (that is a future
`bootstrap`/`runtime` phase's wiring concern) and does not perform collection, parsing,
extraction, analysis, graph construction, or Foundation decisions -- those are `collectors`,
`parsers`, `extractors`, `analyzers`, `graph`, `foundation` (already built), entirely out of
scope here.

Each of the four subpackages -- `filesystem`, `sqlite`, `postgres`, `qdrant` -- provides one
`driver.py` implementing every Port relevant to that backend, following the same
Dependency-Inversion relationship `repository.git.GitRepositoryClient` already has to
`repository.base.RepositoryClient`: consumers depend on the abstract Port (`domain.interfaces.*`,
`vector.base.VectorStore`), never on a concrete driver class directly. `base.py` defines the
shared `StorageError` hierarchy and the deterministic entity (de)serialization helpers every
entity-persisting backend (`filesystem`, `sqlite`, `postgres`) builds on -- `qdrant` does not use
these, since it persists `vector.base.VectorRecord`, not a `domain.entities.Entity`.

Every driver is dependency-injection friendly: a connection, client, or root path is always
passed in explicitly by the caller, never constructed implicitly or held as global state, and
construction itself never performs a network call -- `sqlite`, `postgres`, and `qdrant` each
expose an explicit `initialize()`/`ensure_collection()` step, called separately from
`__init__`, for any one-time schema or collection setup.

Each module here is self-contained and imported directly by its full path (e.g. `from
src.storage.sqlite.driver import SqliteSourceRepositoryStore`); this package intentionally does
not re-export a combined surface from `__init__.py`.
"""
