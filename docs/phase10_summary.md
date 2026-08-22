# VAOS Phase 10 — Storage Layer Summary

**Scope:** `src/storage/__init__.py`, `src/storage/base.py`, plus one
`driver.py` per backend — `filesystem/`, `sqlite/`, `postgres/`,
`qdrant/` — the four-backend structure this phase's own instructions
specified.
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`,
`src/foundation`, and `src/vector` were not modified.**
**`pyproject.toml` was modified once, after an explicit approval step:
`asyncpg>=0.30,<0.31` and `qdrant-client>=1.9,<1.10` were added to
`[project.dependencies]`. No other line in `pyproject.toml` changed. No
source code changed as a result — verification proved none was needed;
see "Dependency declaration" below.**
**Generated:** 2026-08-22 (updated same day, after dependency approval)

## A discrepancy found before writing any code, reported up front

Before touching anything, the repository was inspected as instructed —
cloned fresh, `git log`/`git tag --all` checked. The task brief's
"Current state" section describes Phase 10 as already partially
implemented: Filesystem, SQLite, and PostgreSQL drivers complete, only
Qdrant blocked pending Phase 11's Vector contract. That is not what is
actually in the repository. There was no `src/storage/` directory
anywhere in the history, no `tests/unit/storage/` directory, no
`docs/phase10_summary.md`, and no storage-related dependency in
`pyproject.toml`. The tags jump directly from `v0.9.0` to `v0.11.0`; the
commit log goes straight from "Phase 9: Foundation layer implementation"
to "Phase 11: Vector layer implementation". Phase 11's own summary
(`docs/phase11_summary.md`) independently documents this same finding
from when it was built.

This was reported up front, and you confirmed: build the complete
Phase 10 from scratch against the actual repository state, rather than
"resuming" a prior implementation that was never actually there.
Everything below is a first implementation, not a completion of
pre-existing work.

## Dependency declaration — approved and applied

The first version of this document (and the first `pytest_report.txt`/
`mypy_report.txt`) reported `asyncpg` and `qdrant-client` as required
but undeclared, and deliberately left `pyproject.toml` untouched pending
review, per that step's own explicit instruction not to add a
dependency silently. That report was reviewed, a seven-point decision
report was requested and given (package name, exact version constraint,
rationale, Python ≥3.13 compatibility, sufficiency of a bare
`pyproject.toml` addition, whether any code change would be needed, and
the exact commands to rerun), and the addition was then explicitly
approved. `pyproject.toml`'s `[project.dependencies]` now reads:

```toml
dependencies = [
    "pyyaml>=6.0",
    "asyncpg>=0.30,<0.31",
    "qdrant-client>=1.9,<1.10",
]
```

Nothing else in `pyproject.toml` changed — `requires-python = ">=3.13"`,
`[project.optional-dependencies].dev`, `[tool.mypy]`, `[tool.ruff]`, and
every other section are byte-for-byte what they were.

**Why these exact bounds** (repeated here for a single source of
truth, matching the decision report given before this change was
approved): both lower bounds pin to the exact version this phase's own
driver code was verified against — `asyncpg`'s `connect`/`create_pool`/
`Connection.execute`/`fetch`/`fetchrow` signatures and its exception
hierarchy, and `qdrant-client`'s `AsyncQdrantClient` methods and
`qdrant_client.http.models` shapes, were confirmed via direct
introspection (`inspect.signature`, `model_fields`) of these exact
versions, not assumed from memory or documentation. `asyncpg`'s upper
bound (`<0.31`) is a safety margin — no version above 0.30.0 was tested.
`qdrant-client`'s upper bound (`<1.10`) is a substantive reason, not
just a margin: `search()`, the exact method this driver calls, begins
emitting a deprecation warning in favor of `query_points()` starting at
1.10; the pin keeps the driver on `search()`'s stable, non-deprecated
surface.

**Python ≥3.13 compatibility, stated precisely rather than assumed:**
`asyncpg` 0.30.0's PyPI classifiers list only 3.8–3.12, but its actual
published wheel set includes compiled `cp313` binaries across every
platform, and its `requires_python` metadata (`>=3.8.0`) does not
exclude 3.13 — the classifier list is simply stale, not authoritative.
`qdrant-client` 1.9.2 is a pure-Python wheel (`py3-none-any`, no
compiled extensions) with `requires_python >= 3.8`; being pure Python
substantially lowers (without strictly eliminating) the risk of a real
3.13 incompatibility. Neither package was directly executed on a real
3.13 interpreter as part of this phase's own verification — this
sandbox has only Python 3.12.3 available (see "A note on the Python
version used to run verification," unchanged from before this
approval, and the `pip install -e ".[dev]"` finding immediately below).

**No source code changed as a result of this addition.** Verification
(rerun in full below) confirms `src/storage/postgres/driver.py` and
`src/storage/qdrant/driver.py` needed no change: both already imported
their client unconditionally, and both already carried exactly the
`mypy` accommodations each library's own type-stub situation requires
(`asyncpg` ships no `py.typed` marker, so its `# type: ignore
[import-untyped]` stays; `qdrant-client` does ship proper inline types,
so no equivalent ignore was ever added for it). The only files this
step touched are `pyproject.toml` itself and the four documentation
files this instruction asked to be regenerated.

**`pip install -e ".[dev]"` was run first, exactly as instructed, and
its literal result was:**

```
ERROR: Package 'vaos' requires a different Python: 3.12.3 not in '>=3.13'
```

This is **not** related to today's dependency addition. `requires-python
= ">=3.13"` has been in `pyproject.toml` since the Phase 4 commit
(`0db4b3c`, "Phase 4: Collectors layer implementation" — confirmed via
`git show 0db4b3c:pyproject.toml`), long before this phase existed, and
this sandbox has never had a Python 3.13
interpreter available (Ubuntu noble ships 3.12 as `python3`; no
`python3.13` package exists in its default repos; no PPA is reachable
under this sandbox's network allowlist — confirmed by directly checking
`apt-cache policy python3.13` and `apt-get update` against the allowed
mirrors). Every verification command after this one was instead run
against a virtualenv with `asyncpg==0.30.0` and `qdrant-client==1.9.2`
installed directly (the exact versions the new constraints resolve to),
so every result below reflects the real, now-declared dependency set —
not a workaround of it, only a workaround of this sandbox's own,
pre-existing Python-version ceiling.

## Design decisions made, and why

Nothing here overrides `domain.interfaces` or `vector.base` — every
decision below is this phase's own, filling in a Port those contracts
deliberately left open, exactly as `domain.interfaces.Repository` and
`vector.base.VectorStore` were designed to be filled.

1. **`add`/`update`/`delete` semantics, fixed once and reused across
   every entity-persisting backend.** `domain.interfaces.Repository`'s
   own docstrings distinguish `add` ("persist a *new* entity") from
   `update` ("persist changes to an *existing* entity") but don't state
   what happens on misuse — the reference in-memory stub in
   `tests/unit/domain/test_interfaces.py` blindly overwrites either way,
   adequate for a toy double but not for a real backend. This phase
   settled one concrete, consistent answer, applied identically across
   `filesystem`/`sqlite`/`postgres`: `add` raises `StorageIntegrityError`
   on a duplicate id (or, for `SourceRepository`, a duplicate
   `source_uri`); `update` raises the new `EntityNotFoundError` on a
   missing id; `delete` is a no-op on a missing id, matching
   `vector.base.VectorStore.delete`'s and
   `repository.base.WorkspaceManager.remove`'s own "missing is not an
   error" precedent. A caller can swap backends without observing a
   behavior change.
2. **A shared `storage.base` serialization layer, not three copies.**
   Every entity-persisting backend needs the exact same JSON-safe shape
   per entity (`UUID`s and enums as strings, `datetime`s as ISO-8601,
   `metadata` passed through) — `storage/base.py` fixes that shape once
   (`source_repository_to_dict`/`_from_dict`, and the equivalent pair for
   `SourceFile`, `AnalysisRun`, `Finding`), reused unmodified by
   `filesystem` and `sqlite`, and by `postgres` after one extra
   `json.dumps`/`json.loads` step for its `metadata` column (see
   decision 4). `EntityNotFoundError` lives here too, as a
   `core.exceptions.NotFoundError` subclass rather than a `StorageError`
   subclass — a missing entity is a `NotFoundError` regardless of which
   layer discovers it.
3. **A method-ordering bug worth naming, because it will recur.**
   Concrete classes below implement both a bare `list()` method (from
   `domain.interfaces.Repository`) and a `list_by_*` lookup method
   returning `list[SourceFile]` (etc.). Defining `list()` *before* a
   later `list_by_*` method in the same class body breaks that later
   method's own `-> list[SourceFile]` return annotation: Python resolves
   `list[SourceFile]` at class-body-execution time against whatever `list`
   currently means in that namespace, and by then the class's own `list`
   *method* has already shadowed the builtin, so `list[SourceFile]`
   fails with `TypeError: 'function' object is not subscriptable`. It
   surfaced immediately as an import-time crash while building the
   filesystem driver, was fixed there and pre-emptively fixed in every
   other concrete class by ordering `list_by_*` before `list()` — the
   exact ordering `tests/unit/domain/test_interfaces.py`'s own reference
   stubs already use, which is presumably why this never surfaced
   before Phase 10.
4. **PostgreSQL's schema stores `TEXT`, not native `UUID`/`TIMESTAMPTZ`/
   `JSONB`.** `asyncpg` auto-converts native-typed columns to Python
   `UUID`/`datetime` objects on read, which would require a second,
   Postgres-specific decode path diverging from `storage.base`'s
   string-based shape. Trading native PostgreSQL typing (and whatever
   query-level benefits it offers, unused by this phase's own access
   patterns) for byte-for-byte reuse of the exact same
   `storage.base.*_from_dict` functions `sqlite` uses, with zero
   backend-specific branching, was judged the better trade given this
   phase's own emphasis on consistency across backends.
5. **`sqlite`'s connection needs its own lock; `postgres`/`qdrant`
   don't.** `sqlite3.Connection`, even opened with
   `check_same_thread=False` (required since every operation runs
   inside a worker thread via `asyncio.to_thread`), is not safe for
   *concurrent* use from more than one thread at once — this surfaced as
   a genuine `sqlite3.ProgrammingError` during manual verification
   before any formal test caught it. Fixed by introducing
   `SqliteConnection`, a small dataclass pairing the connection with one
   `asyncio.Lock` every one of the four stores built on it shares.
   `asyncpg` needed no equivalent: it raises its own
   `InterfaceError` (wrapped here as `StorageConnectionError`) rather
   than risking silent corruption if a bare `Connection` is used
   concurrently — callers wanting genuine concurrency inject an
   `asyncpg.Pool` instead, which manages that safely on its own.
6. **Structural `Protocol` client typing for `postgres` and `qdrant`,
   not the concrete client class.** Both drivers type their injected
   client (`_AsyncpgConnectionLike`, `_QdrantClientLike`) as a narrow
   `Protocol` capturing only the methods actually called, rather than
   `asyncpg.Connection | asyncpg.Pool` or `AsyncQdrantClient` directly.
   Both real clients satisfy their Protocol automatically (structural,
   not nominal, typing), so nothing is lost for production use — but it
   is also what let this phase's own tests exercise each driver's real
   SQL-building, point-mapping, and error-wrapping logic against a
   lightweight in-memory fake, with zero live server, exactly matching
   this phase's own "unit tests must not require live external
   services" requirement.
7. **Qdrant: reserved `"entity_id"` payload key, Cosine-only distance,
   and a documented score rescaling.** A point's id is `str(record.id)`
   (Qdrant accepts UUID-formatted strings as point ids natively); its
   payload is `record.metadata` plus one reserved `"entity_id"` key. The
   collection is always created for Cosine distance —
   `vector.base.VectorStore.search`'s own contract requires scores
   normalized to `[0.0, 1.0]`, and Qdrant's raw Cosine score is a
   similarity in `[-1.0, 1.0]`; this driver rescales via
   `(raw + 1.0) / 2.0`, clamped defensively at the boundaries. Both
   choices are documented in the driver's own module docstring, not
   left implicit.

## What this layer does

`storage` answers two questions with one package: *where do domain
entities (`SourceRepository`, `SourceFile`, `AnalysisRun`, `Finding`)
actually live?* and *where do embeddings actually live?* It provides
concrete adapters for both:

- **`storage.filesystem`** — `FilesystemSourceRepositoryStore`,
  `FilesystemSourceFileRepository`, `FilesystemAnalysisRunRepository`,
  `FilesystemFindingRepository`. One JSON file per entity collection
  under an injected root directory, atomic writes (temp file +
  `os.replace`), a per-collection `asyncio.Lock`. No dependency beyond
  the standard library.
- **`storage.sqlite`** — the same four Ports, backed by stdlib
  `sqlite3` via `open_connection`/`initialize_schema`/
  `close_connection` and the `SqliteConnection` wrapper (design
  decision 5). No dependency beyond the standard library.
- **`storage.postgres`** — the same four Ports again, backed by
  `asyncpg` via `connect`/`create_pool`/`initialize_schema`/
  `close_connection`/`close_pool`. Requires `asyncpg` — now declared in
  `[project.dependencies]` (see "Dependency declaration").
- **`storage.qdrant`** — `QdrantVectorStore`, the sole concrete
  implementation of `vector.base.VectorStore` in this codebase, backed
  by `qdrant_client.AsyncQdrantClient`. Requires `qdrant-client` — now
  declared in `[project.dependencies]` (see "Dependency declaration").

It defines no new contract of its own — every class implements an
existing, already-frozen Port (`domain.interfaces.*`,
`vector.base.VectorStore`) rather than inventing one, and it does not
decide *which* backend a running system actually uses (a future
`bootstrap`/`runtime` phase's wiring concern).

## Tests

136 new tests across seven files:

- `tests/unit/storage/test_base.py` (15) — the error hierarchy, and
  full-field round-trip serialization for all four entity types,
  including every optional field (`AnalysisRun.started_at`/
  `completed_at`/`error_message`, `Finding.source_file_id`/`score`) both
  present and `None`.
- `tests/unit/storage/filesystem/test_driver.py` (21) — CRUD, both
  lookup methods, `StorageIntegrityError`/`EntityNotFoundError`, data
  surviving a fresh store instance against the same root, corrupted-JSON
  handling, and a direct check that the backing file is genuinely valid
  JSON with no leftover temp file after a write.
- `tests/unit/storage/sqlite/test_driver.py` (23) — the same CRUD
  matrix plus `source_uri`'s `UNIQUE` constraint, schema idempotency, a
  connection-reuse check across two different store types, 25
  concurrently-`gather`ed reads against the shared lock (design decision
  5), and a query against a closed connection.
- `tests/unit/storage/postgres/test_driver.py` (19) — the same CRUD
  matrix against `FakeAsyncpgConnection`, an in-memory double that
  parses this driver's own small set of SQL shapes (`asyncpg`'s real
  exception types and `"VERB <count>"` status-string convention), plus a
  connection-failure path and a check that every entity's declared
  column tuple matches its `storage.base` serializer's own keys.
- `tests/unit/storage/qdrant/test_driver.py` (26) — every item the
  original task brief's own Qdrant testing checklist named: construction
  (no network call), configuration, upsert, get, delete, `exists`,
  similarity search (ordering, `limit`, metadata filter, empty results,
  `[0.0, 1.0]`-normalized scores, determinism across repeated calls),
  metadata round-trip mapping, invalid inputs (dimension mismatch on
  both `upsert` and `search`), client errors, and `aclose`.
- `tests/unit/storage/test_dependency_boundaries.py` (22) — see
  "Architectural verification."
- `tests/unit/storage/test_imports.py` (10) — see "Architectural
  verification."

**A second import-collision fix, found before the dependency was
declared and kept afterward as a defensive guard.** `postgres/
test_driver.py` and `qdrant/test_driver.py` originally imported
`asyncpg`/`qdrant_client` directly at module level for their own
fake-client/exception-type needs. Since `src.storage.postgres.driver`/
`src.storage.qdrant.driver` themselves also import those packages
unconditionally, a missing dependency turned into a pytest *collection*
error — which, by default, aborts the entire test session, not just
those two files. Both test files start with a module-level
`pytest.importorskip(...)` guard (matching `test_imports.py`'s own
pattern) before importing anything dependency-gated. Now that
`asyncpg`/`qdrant-client` are genuinely declared, neither guard ever
fires in this project's own normal install — both packages are always
present, so both files always run for real, confirmed under "Quality
gates," below — but the guard is left in place as cheap, harmless
protection against a future environment that installs this project
without its full dependency set for some other reason.

## Architectural verification

1. **Storage imports** — every `src.storage` module's import statements
   were checked via `ast`, resolving *both* absolute imports and the
   relative `from ..base import ...` imports `filesystem`/`sqlite` use
   (a check that only looked at absolute imports, as
   `tests.unit.vector.test_dependency_boundaries` and
   `tests.unit.foundation.test_dependency_boundaries` do, would silently
   miss those). Every `src.*` import resolves to `src.core`,
   `src.domain`, `src.vector`, or `src.storage` itself; no forbidden
   layer (`repository`, `collectors`, `parsers`, `extractors`,
   `analyzers`, `graph`, `foundation`, and every not-yet-built package)
   is imported anywhere.
2. **No circular dependencies** — the four backend subpackages
   (`filesystem`, `sqlite`, `postgres`, `qdrant`) do not import from one
   another; each is self-contained, sharing only `storage.base`.
3. **Storage → Vector, not Vector → Storage** — `storage.qdrant.driver`
   imports `src.vector.base` (to implement `VectorStore`); `src/vector`
   was independently confirmed to import nothing from `src.storage`
   (unchanged from Phase 11 — see point 5).
4. **Nothing outside storage imports storage** — every other `src`
   package was scanned; none imports anything from `src.storage`,
   confirming it sits as an outer/leaf layer, as intended.
5. **Phase 1–9 and Phase 11 remain unchanged** — confirmed via
   `git diff --stat HEAD` and `git diff HEAD --name-only` against every
   frozen package plus `pyproject.toml`: empty diff, zero modified
   lines, in both directions.

## Quality gates

All results below are from the post-approval, dependency-declared state
(`asyncpg==0.30.0`, `qdrant-client==1.9.2` genuinely installed, matching
`pyproject.toml`'s new constraints), rerun in full after the
`pyproject.toml` change:

`pip install -e ".[dev]"`: fails on this sandbox's pre-existing Python
3.12.3-vs-`>=3.13` gate, unrelated to this dependency addition (see
"Dependency declaration," above, for the full explanation). Every
command below ran against a venv with the exact resolved versions
installed directly instead.

`pytest tests/unit/storage/test_imports.py -v`: 10/10 passed, 0
skipped — both dependency-gated parametrized cases (`storage.postgres`,
`storage.qdrant`) now import and pass for real, no longer skip.

`pytest tests/unit/storage/ -v`: 136/136 passed, 0 skipped, 0 failed —
including `storage/postgres/` (19/19) and `storage/qdrant/` (26/26)
individually reconfirmed with zero skips.

`pytest tests/ -q`: 1008/1008 passed (up from 872 before this phase),
0 skipped, 0 failed.

`mypy --strict --python-version 3.13 src/storage/ tests/unit/storage/`:
clean, 23 source files.

`mypy --strict --python-version 3.13 src/ tests/`: clean, 205 source
files.

`ruff check src/storage/ tests/unit/storage/`: clean, all checks
passed.

`ruff check .`: exactly the one pre-existing `UP046` finding in frozen
`src/domain/interfaces.py` that already predates Phase 9 (see
`phase9_summary.md`, reconfirmed unchanged by Phase 11 and again here)
— nothing new introduced by this phase or by today's dependency
addition.

Also separately reconfirmed: dependency-boundary and
circular-dependency tests (`test_dependency_boundaries.py`, 22/22
passed); `git diff --stat HEAD` shows only `pyproject.toml` and this
phase's own three regenerated report files changed among tracked
files — Phase 1–9 and Phase 11 are unchanged (`git diff HEAD --
name-only` against every frozen path is empty). Full output for every
command above is in `docs/pytest_report.txt`, `docs/mypy_report.txt`,
and `docs/ruff_report.txt`.

## A note on the Python version used to run verification

This sandboxed environment has Python 3.12.3 available; no 3.13
interpreter is installable here — the same substitution already noted,
unremarked, in every prior phase's own `pytest_report.txt`. Dev tools
(`pytest`, `pytest-asyncio`, `mypy`, `ruff`) were installed standalone
and run directly against the source tree, relying on
`[tool.pytest.ini_options] pythonpath = ["."]`. `mypy --strict` was run
with an explicit `--python-version 3.13` flag throughout, matching
`pyproject.toml`'s own `[tool.mypy] python_version = "3.13"`. No
3.13-exclusive syntax was used anywhere in this phase's code.

## Package contents added this phase

```
src/storage/
├── __init__.py
├── base.py                (StorageError hierarchy; *_to_dict/*_from_dict per entity)
├── filesystem/
│   ├── __init__.py
│   └── driver.py           (FilesystemSourceRepositoryStore, FilesystemSourceFileRepository,
│                             FilesystemAnalysisRunRepository, FilesystemFindingRepository)
├── sqlite/
│   ├── __init__.py
│   └── driver.py           (SqliteConnection, open_connection, initialize_schema,
│                             close_connection, SqliteSourceRepositoryStore,
│                             SqliteSourceFileRepository, SqliteAnalysisRunRepository,
│                             SqliteFindingRepository)
├── postgres/
│   ├── __init__.py
│   └── driver.py           (connect, create_pool, initialize_schema, close_connection,
│                             close_pool, PostgresSourceRepositoryStore,
│                             PostgresSourceFileRepository, PostgresAnalysisRunRepository,
│                             PostgresFindingRepository)  -- requires asyncpg (declared)
└── qdrant/
    ├── __init__.py
    └── driver.py            (QdrantVectorStore, QdrantOperationError)  -- requires qdrant-client (declared)

tests/unit/storage/
├── __init__.py
├── _fixtures.py                     (shared entity builders, not a test file itself)
├── test_base.py                     (15 tests)
├── test_dependency_boundaries.py    (22 tests)
├── test_imports.py                  (10 tests)
├── filesystem/
│   ├── __init__.py
│   └── test_driver.py               (21 tests)
├── sqlite/
│   ├── __init__.py
│   └── test_driver.py               (23 tests)
├── postgres/
│   ├── __init__.py
│   └── test_driver.py               (19 tests)
└── qdrant/
    ├── __init__.py
    └── test_driver.py                (26 tests)
```

## What this layer does NOT do

Beyond adding `asyncpg`/`qdrant-client` to `[project.dependencies]` (see
"Dependency declaration," approved and applied above), no other line of
`pyproject.toml` changed, and no source code changed — verification
proved none was required. No Domain or Vector contract was modified,
duplicated, or reinterpreted — every concrete class implements an
existing, frozen Port exactly as given. No wiring, bootstrap, or "which
backend is actually running" decision was made — that is out of scope
for this phase, same as it was for `vector`. Every other not-yet-built
package (`memory`, `pipeline`, `api`, `cli`, `plugins`, `application`,
`bootstrap`) — none were touched.

---

**Phase 10 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`,
`src/graph`, `src/foundation`, and `src/vector` unmodified.
`pyproject.toml` modified once, after explicit approval, adding exactly
`asyncpg>=0.30,<0.31` and `qdrant-client>=1.9,<1.10` to
`[project.dependencies]` — nothing else in that file changed, and no
source code changed as a result. `storage.postgres`/`storage.qdrant`
tests now run unconditionally, zero skips, confirmed above. No genuine
contract gap encountered; seven design decisions and one real
concurrency bug (found and fixed before any test caught it) are
reported above rather than left implicit. No Git tag created, no commit
made, phase not auto-frozen.**

**PHASE 10 READY FOR FREEZE**
