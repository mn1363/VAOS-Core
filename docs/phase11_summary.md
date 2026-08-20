# VAOS Phase 11 — Vector Layer Summary

**Scope:** `src/vector/__init__.py`, `src/vector/base.py` — a single
`base.py`, no subpackages, exactly the flat target tree this phase's own
instructions specified (`src/vector/base.py`, nothing more).
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`, and
`src/foundation` were not modified.**
`pyproject.toml` was not modified — no new dependency was needed (no
external runtime dependency at all, per this phase's own requirement).
**Generated:** 2026-08-20

## A discrepancy found before writing any code, reported up front

Before touching anything, the repository was inspected as instructed —
cloned fresh, then unshallowed to check its **full** history (every
branch, every tag). The task brief's "Current state" section describes
Phase 10 (Storage) as already implemented: Filesystem, SQLite, and
PostgreSQL complete, Qdrant intentionally blocked. That is not what is
actually in the repository. There is no `src/storage/` directory
anywhere in the history, no `docs/phase10_summary.md`, and no
storage-related dependency in `pyproject.toml`. The last real commit and
tag is `v0.9.0` (Phase 9 — Foundation); nothing beyond it exists on any
branch or tag.

This was reported to the user before any implementation began. It does
not, however, constitute a STOP condition for this phase specifically:
Vector's own dependency rule is `Vector → Core/Domain`, explicitly
*not* `Vector → Storage` (storage drivers depend on Vector, never the
reverse), so Phase 10's absence changes nothing about what this phase
needed to inspect or build. It matters for whatever phase eventually
wires a concrete `VectorStore` into a real backing store — that phase
will first need Phase 10 to actually exist.

## No contract gap; two contract-shaped design decisions reported up front

`src/core` and `src/domain` were fully inspected before writing anything
(`core.exceptions`, `core.protocols`, `core.logging`; `domain.entities`,
`domain.dtos`, `domain.interfaces`), alongside every existing Port's own
`base.py` (`domain.interfaces.Repository`, `foundation.ranking.base`,
`repository.base.RepositoryClient`) for established conventions. No
existing Domain entity needed modification and no existing contract was
duplicated — `VectorRecord` is a new, freestanding value object, not a
`domain.entities.Entity` subclass (it is immutable and lifecycle-free,
unlike every `Entity`, which is deliberately mutable with its own
`touch()`-driven `updated_at`).

Two decisions were required rather than found ready-made:

1. **Two identifiers, not one.** The brief's own "Vector record" bullet
   list names both "a stable identifier" and, separately, "associated
   entity/document identity" — two distinct concepts. `VectorRecord`
   therefore carries `id: UUID` (the vector record's own identity) and
   `entity_id: UUID` (the identifier of the domain entity it represents,
   e.g. a future `SourceFile.id`) as two independent fields, so a single
   entity may in principle be represented by more than one vector record
   (one per chunk of a large file), each with its own independent
   lifecycle. `entity_id` reuses `domain.entities.Entity.id`'s own name
   and type without importing `domain.entities` itself — the same
   allowed-but-unused relationship to `src.domain`
   `foundation.comparer.base.FoundationSubject.repository_id` already
   established relative to `domain.entities.SourceFile.repository_id`.
2. **A dimension-mismatch exception, and where it lives.** The brief
   asks for "explicit validation" and "clear VAOS-compatible exceptions"
   but does not by itself require a bespoke exception type. Embedding
   dimensionality mismatches (a batch upsert, or a query, against a
   store that enforces one fixed dimensionality) are common enough and
   distinct enough from generic validation failures that a dedicated
   `VectorDimensionMismatchError(ValidationError)` was added — narrow
   enough to stay catchable as a plain `ValidationError` too, and paired
   with one `require_matching_dimensions` helper a concrete store can
   call before a batch upsert, mirroring
   `foundation.ranking.base.require_unique_subjects`'s own role.

## What this layer does

`vector` answers one question: *what does it mean to persist an
embedding and search for the ones most similar to a query, independent
of which concrete vector database eventually backs it?* `base.py`
defines:

- **`VectorRecord`** — frozen, slotted: `id`, `entity_id`, `embedding:
  tuple[float, ...]` (validated non-empty and finite-valued), `metadata:
  dict[str, Any]`, plus a `dimensions` property.
- **`SimilaritySearchRequest`** — frozen, slotted: `query_embedding`,
  `limit` (positive, defaults to 10), `metadata_filter` (exact-match,
  defaults to empty), plus a `dimensions` property. Validated the same
  way as `VectorRecord.embedding`.
- **`SimilaritySearchMatch`** — frozen, slotted: a `VectorRecord` paired
  with a `score` normalized to `[0.0, 1.0]` (higher is more similar,
  metric-agnostic per concrete store).
- **`SimilaritySearchResult`** — frozen, slotted: `matches`, validated as
  sorted by `(-score, record.id)` and free of duplicate records at
  construction time — deterministic regardless of a concrete store's own
  internal ordering — mirroring
  `foundation.ranking.base.FoundationRanking`'s `(-value, subject_id)`
  convention exactly. Exposes `match_count` and `top(count)`.
- **`VectorStore(ABC)`** — the Port: `upsert`, `get`, `delete`, `exists`,
  `search`, `aclose`, every method `async` (matching
  `domain.interfaces.Repository`'s own async persistence Port, since a
  concrete implementation is expected to perform I/O). `aclose` matches
  `core.protocols.SupportsAsyncClose`'s shape structurally rather than
  formally inheriting from it.
- **`VectorDimensionMismatchError`** and **`require_matching_dimensions`**
  — see design decision 2, above.

It does not implement Qdrant, add a Qdrant (or any other) client
dependency, implement a vector database, or create any storage
infrastructure — see "What this layer does NOT do," below.

## Tests

`tests/unit/vector/test_base.py` (40 tests) covers every area the brief
asked for: `VectorRecord` construction, immutability, value-equality, and
embedding validation (empty, NaN, infinite); `SimilaritySearchRequest`
defaults and validation; `SimilaritySearchMatch`/`SimilaritySearchResult`
score bounds, deterministic ordering, duplicate rejection, and `top()`;
`require_matching_dimensions`; abstractness of `VectorStore`; and a
`_InMemoryVectorStore` test double — used, per the same precedent as
`tests/unit/domain/test_interfaces.py`'s own `_InMemorySourceRepositoryStore`,
only to prove the contract is genuinely implementable, not as a
production adapter — exercising the full upsert/get/exists/delete
round trip, upsert-overwrite, dimension-mismatch rejection on both
upsert and search, brute-force cosine similarity search with
correct ordering, `limit`, and `metadata_filter`, `aclose`, and
`isinstance(..., SupportsAsyncClose)` structural conformance.

`tests/unit/vector/test_dependency_boundaries.py` (5 tests, parametrized
by source file) statically scans every `src/vector` module's import
statements via `ast`: no forbidden layer is imported, every `src.*`
import resolves to `src.core`/`src.domain`/`src.vector`, and — as an
explicit, single-purpose guard for the one relationship this phase must
never invert — `src.storage` is never imported anywhere in the package.

`tests/unit/vector/test_imports.py` (2 tests) verifies `src.vector` and
`src.vector.base` both import cleanly by execution, matching
`tests/unit/foundation/test_imports.py`'s own pattern.

## Architectural verification

1. **Vector imports** — `src/vector/base.py` imports only `math`
   (stdlib), `abc`, `collections.abc.Sequence`, `dataclasses`,
   `typing.Any`, `uuid.UUID` (stdlib), and `src.core.exceptions`,
   `src.core.logging` (allowed). `src.domain` is an allowed dependency
   but is not imported — `entity_id: UUID` reuses `domain.entities.
   Entity.id`'s field name/type without importing the entity class
   itself (see design decision 1) — the same allowed-but-unused pattern
   `graph.knowledge.base` and every `foundation.*.base` module already
   established relative to `src.domain`.
2. **Vector → Core/Domain boundaries** — confirmed by (1) and by
   `test_vector_module_imports_only_allowed_layers`.
3. **No Vector → Storage dependency** — confirmed by
   `test_vector_does_not_import_storage_anywhere` and by (1): `src.
   storage` appears nowhere in `src/vector`.
4. **No circular dependencies** — `src/vector` has a single substantive
   module (`base.py`); no intra-package cycle is possible.
5. **Frozen Phase 1–9 files remain unchanged** — confirmed via `git
   diff --stat` against every frozen package (`src/core`, `src/domain`,
   `src/repository`, `src/collectors`, `src/parsers`, `src/extractors`,
   `src/analyzers`, `src/graph`, `src/foundation`): empty diff.
6. **Phase 10** — does not exist in this repository (see the discrepancy
   noted above), so trivially unchanged.

## Quality gates

`pytest`: 47 new tests, all passing; full repository suite (Phase 1–9,
11 combined; Phase 10 not yet built) at 872 passing, 0 failing. Full
output in `docs/pytest_report.txt`.

`mypy --strict --python-version 3.13`: `src/vector` + `tests/unit/vector`
clean (6 source files); full repository clean (182 source files, up from
176 before this phase). Full output in `docs/mypy_report.txt`.

`ruff check`: `src/vector` + `tests/unit/vector` clean; full repository
shows exactly the one pre-existing `UP046` finding in frozen
`src/domain/interfaces.py` that already predates Phase 9 (confirmed
against the Phase 8 baseline in `phase9_summary.md`) — nothing new
introduced by this phase. Full output in `docs/ruff_report.txt`.

## A note on the Python version used to run verification

This sandboxed environment has Python 3.12.3 available; no 3.13
interpreter is installable here. This is the same substitution already
present, unremarked, in every prior phase's own `pytest_report.txt` (see
Phase 9's own note on this), so it is not a new deviation introduced
here. `pyproject.toml` pins `requires-python = ">=3.13"` at the package
level, so — rather than editing that pin or installing the `vaos`
package itself — the dev tools (`pytest`, `pytest-asyncio`, `mypy`,
`ruff`) were installed standalone and run directly against the source
tree, relying on `[tool.pytest.ini_options] pythonpath = ["."]` for test
discovery. `mypy --strict` was run with an explicit `--python-version
3.13` flag (mypy's target semantics are governed by this flag,
independent of the interpreter running mypy itself), matching
`pyproject.toml`'s own `[tool.mypy] python_version = "3.13"`. No
3.13-exclusive syntax was used anywhere in this phase's code.

## Package contents added this phase

```
src/vector/
├── __init__.py    (package docstring only, no re-exports)
└── base.py         (VectorRecord, SimilaritySearchRequest, SimilaritySearchMatch,
                      SimilaritySearchResult, VectorStore, VectorDimensionMismatchError,
                      require_matching_dimensions)

tests/unit/vector/
├── __init__.py
├── test_base.py                    (40 tests)
├── test_dependency_boundaries.py   (5 tests)
└── test_imports.py                 (2 tests)
```

## What this layer does NOT do

No Qdrant client dependency was added; no vector database was
implemented; no storage infrastructure was created. `VectorStore` is a
Port only — no concrete implementation lives in `src/vector` (the
`_InMemoryVectorStore` used to prove the contract is implementable lives
entirely inside `tests/unit/vector/test_base.py`, outside the package,
matching `tests/unit/domain/test_interfaces.py`'s own precedent). Every
other not-yet-built package (`storage`, `memory`, `pipeline`, `api`,
`cli`, `plugins`, `application`, `bootstrap`) — none were touched.

---

**Phase 11 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`,
`src/graph`, and `src/foundation` unmodified. No genuine contract gap
encountered; one pre-implementation discrepancy (Phase 10's absence from
the actual repository) and two contract-shaped design decisions
(`VectorRecord`'s two-identifier split; `VectorDimensionMismatchError`'s
scope) reported above rather than left implicit. No Git tag created, no
commit made, phase not auto-frozen. Next phase not started — awaiting
your instruction.**

**PHASE 11 READY FOR FREEZE**
