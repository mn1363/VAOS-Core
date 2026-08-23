# VAOS Phase 12 — Memory Layer Summary

**Scope:** `src/memory/__init__.py`, `src/memory/base.py` — a single
`base.py`, no subpackages, exactly the flat target tree this phase's
own instructions specified (`src/memory/base.py`, nothing more).
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`,
`src/foundation`, `src/storage`, and `src/vector` were not modified.**
`pyproject.toml` was not modified — no new dependency was needed (no
external runtime dependency at all, per this phase's own requirement).
**Generated:** 2026-08-23

## Repository inspected first; no contract gap found

Before writing any code, the repository was cloned fresh from
`https://github.com/mn1363/VAOS-Core` (`main`, commit `54e6d06`,
"Phase 10: Storage layer implementation") and every layer this phase's
own brief named was inspected: `src/core` (`exceptions.py`,
`protocols.py`, `logging.py`, `constants.py`), `src/domain`
(`entities.py`, `dtos.py`, `interfaces.py`), `src/repository/base.py`,
`src/graph/knowledge/base.py`, `src/foundation/__init__.py` and
`src/foundation/ranking/base.py`, `src/storage/base.py` and
`src/storage/__init__.py`, and — most heavily, as Memory's closest
architectural sibling — `src/vector/__init__.py` and
`src/vector/base.py` in full, plus its test suite
(`tests/unit/vector/test_base.py`, `test_dependency_boundaries.py`,
`test_imports.py`). Phase 10 (Storage) and Phase 11 (Vector) both
exist in the repository at this commit, each frozen and tagged per
their own summaries — no discrepancy comparable to the one Phase 11's
own summary reported (Phase 10's absence at that time) was found here.

No required contract was missing. Every value Memory needed — the
`VAOSError`/`ValidationError` hierarchy, `get_logger`,
`SupportsAsyncClose`'s shape — already existed in `core`, exactly as
`vector.base` had already used them. No existing Domain entity needed
modification and no existing contract was duplicated.

## Design decisions made, and why each one is the minimal, best-precedented choice

Four decisions were required rather than found ready-made. Each is
documented in `src/memory/base.py`'s own module docstring at the point
it applies; summarized here:

1. **`MemoryRecord` is a new, freestanding value object, not a
   `domain.entities.Entity` subclass.** Every `Entity` is mutable,
   with its own `touch()`-driven `updated_at` and, on some subclasses,
   explicit state-transition methods enforcing a status machine (e.g.
   `SourceRepository.mark_ready`). Nothing in this phase's brief calls
   for a comparable status machine — a memory record is either stored
   or it is not, and `MemoryStore.upsert`/`delete` already express
   that fully. `MemoryRecord` is therefore a frozen, slotted
   dataclass, mirroring `vector.base.VectorRecord`'s own precedent
   exactly, for the same reason.
2. **`entity_id: UUID | None`, optional rather than mandatory.**
   `VectorRecord.entity_id` is mandatory — every embedding represents
   some entity. A piece of project knowledge need not be about any
   single collected entity (it may be about the project as a whole),
   so `MemoryRecord.entity_id` defaults to `None`. It still reuses
   `domain.entities.Entity.id`'s own field name and type without
   importing the entity class itself — the same allowed-but-unused
   relationship to `src.domain` that `VectorRecord.entity_id`,
   `foundation.comparer.base.FoundationSubject.repository_id`, and
   `graph.knowledge.base`'s own `KnowledgeNode` design already
   established.
3. **`memory_type: str`, a plain string rather than a fixed enum.**
   Matches `domain.entities.Finding.category`'s own precedent and
   stated justification exactly: the exact taxonomy of memory kinds
   belongs to whichever future layer produces or consumes memory
   records (a not-yet-built `pipeline`, `application`, or `plugins`
   phase), not to this Port. Validated non-blank in
   `MemoryRecord.__post_init__`, matching every other freeform-label
   field across the codebase (`Finding.category`, `Finding.message`,
   `SourceRepository.name`).
4. **Timestamps, not a version counter.** The brief names both as
   acceptable ("timestamps or version information if required").
   `created_at`/`updated_at` reuse `domain.entities.Entity`'s own two
   field names, types, and `datetime.now(UTC)` default-factory
   convention without importing `Entity` itself. A monotonic version
   counter was not added: nothing in the existing frozen architecture
   reads or enforces one anywhere upstream of this phase (no
   optimistic-concurrency requirement exists), so adding one would
   have been speculative functionality the brief explicitly asks to
   avoid.

One further, smaller decision: `MemoryQueryResult.records` is ordered
deterministically by **ascending `id` alone**, not by a
`(-score, id)` pair the way `vector.base.SimilaritySearchResult` and
`foundation.ranking.base.FoundationRanking` are. Both of those exist
to rank scored candidates; `MemoryQuery` performs no scoring — it is
a deterministic, exact-match filter request, explicitly not a
similarity search (semantic/vector search over memory content is
`vector`'s concern, out of scope here per the brief) — so there is no
score to order by, and inventing one (e.g. recency-based ranking) was
avoided as unrequested, speculative behavior.

## What this layer does

`memory` answers one question: *what does it mean to persist a single
piece of structured project knowledge, and to deterministically
retrieve the ones matching a given set of criteria, independent of
which concrete backend eventually stores it?* `base.py` defines:

- **`MemoryRecord`** — frozen, slotted: `id: UUID`, `memory_type: str`
  (validated non-blank), `content: dict[str, Any]` (the structured
  knowledge payload), `metadata: dict[str, Any]` (freeform,
  descriptive context, filterable), `entity_id: UUID | None` (optional
  reference to a `domain.entities.Entity.id`), `created_at`/
  `updated_at: datetime` (default to `datetime.now(UTC)`).
- **`MemoryQuery`** — frozen, slotted: `memory_type: str | None`,
  `entity_id: UUID | None`, `metadata_filter: dict[str, Any]`
  (exact-match, defaults to empty), `limit: int` (positive, defaults
  to 100). Every constraint is optional and combines with logical AND;
  a default `MemoryQuery()` requests every record up to `limit`.
- **`MemoryQueryResult`** — frozen, slotted: `records`, validated as
  sorted by ascending `id` and free of duplicates at construction
  time. Exposes `record_count` and `top(count)`.
- **`MemoryStore(ABC)`** — the Port: `upsert`, `get`, `delete`,
  `exists`, `query`, `aclose`, every method `async` (matching
  `domain.interfaces.Repository`'s and `vector.base.VectorStore`'s own
  async persistence Ports). `delete` on a missing id is a no-op,
  matching `VectorStore.delete`'s own precedent. `aclose` matches
  `core.protocols.SupportsAsyncClose`'s shape structurally rather than
  formally inheriting from it.
- **`matches_query(record, query) -> bool`** — a shared filter-
  evaluation helper every concrete store's `query` implementation can
  call, so exact-match semantics are defined identically everywhere,
  mirroring `vector.base.require_matching_dimensions`'s own role of
  giving every implementation one shared definition to call rather
  than re-derive.

It does not implement a database, file store, or cache; does not
perform semantic/vector search (that stays `vector`'s exclusive
concern — `MemoryQuery` is an exact-match filter, not a similarity
query); does not add any embeddings responsibility to Memory; and does
not duplicate `VectorRecord` or any vector-search contract — see "What
this layer does NOT do," below.

## Tests

`tests/unit/memory/test_base.py` (38 tests) covers every area the
brief asked for: `MemoryRecord` construction, immutability,
value-equality, and validation (blank/whitespace-only `memory_type`);
identity (`id` vs. `entity_id` distinction); `content`/`metadata`
preservation; independent timestamp defaults; `MemoryQuery` defaults
and validation (blank `memory_type`, non-positive `limit`);
`matches_query` against every constraint individually and combined,
including an absent metadata key; `MemoryQueryResult` ordering,
duplicate rejection, and `top()`; abstractness of `MemoryStore`; and
an `_InMemoryMemoryStore` test double — used, per the same precedent
as `tests/unit/vector/test_base.py`'s own `_InMemoryVectorStore`, only
to prove the contract is genuinely implementable, not as a production
adapter — exercising the full upsert/get/exists/delete round trip,
upsert-overwrite, deterministic query ordering independent of
insertion order, `limit`, each filter individually
(`memory_type`/`entity_id`/`metadata_filter`), a no-match case,
`aclose`, and `isinstance(..., SupportsAsyncClose)` structural
conformance.

`tests/unit/memory/test_dependency_boundaries.py` (6 tests,
parametrized by source file plus two explicit single-purpose guards)
statically scans every `src/memory` module's import statements via
`ast`: no forbidden layer is imported, every `src.*` import resolves
to `src.core`/`src.domain`/`src.vector`/`src.memory`, and — as
explicit, single-purpose guards for the two relationships this phase
must never invert — `src.storage` and `src.repository` are never
imported anywhere in the package.

`tests/unit/memory/test_imports.py` (2 tests) verifies `src.memory`
and `src.memory.base` both import cleanly by execution, matching
`tests/unit/vector/test_imports.py`'s own pattern.

## Architectural verification

1. **Memory imports** — `src/memory/base.py` imports only `abc`,
   `dataclasses`, `datetime`, `typing.Any`, `uuid.UUID` (stdlib), and
   `src.core.exceptions`, `src.core.logging` (allowed);
   `src/memory/__init__.py` imports nothing at all (a docstring-only
   module). Confirmed both by manual `ast`-walk inspection and by
   `test_memory_module_imports_no_forbidden_layer`/
   `test_memory_module_imports_only_allowed_layers`. `src.domain` and
   `src.vector` are allowed dependencies but are not imported —
   `entity_id: UUID` reuses `domain.entities.Entity.id`'s field
   name/type, and nothing requires a `vector.base.VectorRecord`
   reference (see design decisions 2 and the module docstring's own
   "does not embed or reference `VectorRecord`" note) — the same
   allowed-but-unused pattern `vector.base` itself established
   relative to `src.domain`.
2. **Memory → Core/Domain/Vector boundaries** — confirmed by (1) and
   by `test_memory_module_imports_only_allowed_layers`.
3. **No Memory → Storage/Repository dependency** — confirmed by
   `test_memory_does_not_import_storage_anywhere`,
   `test_memory_does_not_import_repository_anywhere`, and by (1):
   neither `src.storage` nor `src.repository` appears anywhere in
   `src/memory`.
4. **No circular dependencies** — `src/memory` has a single
   substantive module (`base.py`) with zero intra-package imports; no
   cycle is possible.
5. **No duplicate Vector contracts** — confirmed by inspection: no
   `VectorRecord`, `SimilaritySearchRequest`, `SimilaritySearchMatch`,
   `SimilaritySearchResult`, or `embedding` field is defined anywhere
   in `src/memory`; every mention of those names in `base.py`'s
   docstrings is a cross-reference to the existing Phase 11 contract,
   not a redefinition.
6. **Frozen Phase 1–11 files remain unchanged** — confirmed via
   `git diff --stat` against every frozen package (`src/core`,
   `src/domain`, `src/repository`, `src/collectors`, `src/parsers`,
   `src/extractors`, `src/analyzers`, `src/graph`, `src/foundation`,
   `src/storage`, `src/vector`), `pyproject.toml`, `configs/`, every
   `docs/phaseN_summary.md` (1–11), `docs/architecture_audit.md`,
   `docs/dependency_graph.md`, and every existing `tests/unit/*`
   directory other than the new `tests/unit/memory/`: empty diff
   throughout. `git status --short` confirms the complete set of
   changes this phase made: `src/memory/` and `tests/unit/memory/`
   (new), `docs/phase12_summary.md` (new), and `docs/pytest_report.txt`
   / `docs/mypy_report.txt` / `docs/ruff_report.txt` (modified) —
   the three shared, not phase-numbered, report files this phase's own
   brief requires regenerating with the current full-suite output,
   matching the convention already established by every prior phase
   (there is one `docs/pytest_report.txt`, not one per phase, unlike
   `docs/phaseN_summary.md`).

## Quality gates

`pytest`: 46 new tests, all passing; full repository suite (Phase
1–12 combined) at **1054 passing, 0 failing, 0 skipped**. Full output
in `docs/pytest_report.txt`.

`mypy --strict --python-version 3.13`: `src/memory` + `tests/unit/memory`
clean (6 source files); full repository clean (**211 source files, 0
errors**). Full output in `docs/mypy_report.txt`.

`ruff check`: `src/memory` + `tests/unit/memory` clean; full
repository shows exactly the one pre-existing `UP046` finding in
frozen `src/domain/interfaces.py` that already predates this phase
(documented as pre-existing in both Phase 9's and Phase 11's own
summaries) — nothing new introduced here. Full output in
`docs/ruff_report.txt`.

## A note on the verification environment

This sandboxed environment started this session with `pytest`,
`pytest-asyncio`, `mypy`, `ruff`, and `pyproject.toml`'s own pinned
runtime dependencies (`asyncpg`, `qdrant-client`) all absent; they
were installed standalone (matching the substitution already
unremarked in every prior phase's own report — see Phase 11's note on
this exact pattern for the Python-interpreter-version case) before
any verification was run, and before any Phase 12 code was written.
Installing `asyncpg`/`qdrant-client` had two side effects, neither
caused by this phase's own code: it moved the full-suite pytest count
from a 959-passed/6-skipped baseline to 1008 passed (0 skipped)
*before* Memory's own 46 tests were added — six tests that were
skipping for a missing dependency now run and pass, plus additional
previously-uncollectable parametrized cases became collectable — and
it resolved the 4 `asyncpg`-stub-related mypy findings a first,
partial dependency install had left (see below), leaving the full
repository mypy-clean. `git diff --stat` confirms zero source-level
change to any frozen file caused either effect; both are purely
environment-installation artifacts of running full verification in a
fresh sandbox. This sandbox has Python 3.12.3 available, matching
Phase 9's/Phase 11's own already-documented substitution; `mypy
--strict` was run with an explicit `--python-version 3.13` flag
throughout, matching `pyproject.toml`'s own `[tool.mypy]
python_version = "3.13"`. No 3.13-exclusive syntax was used anywhere
in this phase's code.

## Package contents added this phase

```
src/memory/
├── __init__.py    (package docstring only, no re-exports)
└── base.py         (MemoryRecord, MemoryQuery, MemoryQueryResult,
                      MemoryStore, matches_query)

tests/unit/memory/
├── __init__.py
├── test_base.py                    (38 tests)
├── test_dependency_boundaries.py   (6 tests)
└── test_imports.py                 (2 tests)
```

## What this layer does NOT do

No database, file store, or cache was implemented; `MemoryStore` is a
Port only — no concrete implementation lives in `src/memory` (the
`_InMemoryMemoryStore` used to prove the contract is implementable
lives entirely inside `tests/unit/memory/test_base.py`, outside the
package, matching `tests/unit/vector/test_base.py`'s own precedent).
No semantic or vector search was implemented — `MemoryQuery` is a
deterministic, exact-match filter, never a similarity query; that
concern stays exclusively `vector`'s. No embedding responsibility was
added to `MemoryRecord`. No `VectorRecord` or vector-search contract
was duplicated. `pyproject.toml` was not touched. Every other
not-yet-built package (`pipeline`, `api`, `cli`, `plugins`,
`application`, `bootstrap`) was not touched.

---

**Phase 12 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`,
`src/graph`, `src/foundation`, `src/storage`, and `src/vector`
unmodified. No genuine contract gap encountered; four design
decisions (`MemoryRecord`'s non-`Entity` freestanding shape;
`entity_id`'s optionality; `memory_type`'s freeform-string shape;
timestamps over a version counter) plus one ordering decision
(`MemoryQueryResult` sorted by `id` alone, no invented score) reported
above rather than left implicit. No Git tag created, no commit made,
phase not auto-frozen. Phase 13 not started — awaiting your
instruction.**

**PHASE 12 READY FOR FREEZE**
