# VAOS Phase 15 — Bootstrap Layer Summary

**Scope:** `src/bootstrap/__init__.py`, `src/bootstrap/errors.py`,
`src/bootstrap/wiring.py` — plus three authorized, test-only
corrections to already-frozen dependency-boundary tests
(`tests/unit/pipeline/test_dependency_boundaries.py`,
`tests/unit/application/test_dependency_boundaries.py`,
`tests/unit/storage/test_dependency_boundaries.py`); no Phase 1–14
*production* code was touched.
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`,
`src/foundation`, `src/storage`, `src/vector`, `src/memory`,
`src/pipeline`, and `src/application` were not modified.**
`pyproject.toml` was not modified — every dependency Bootstrap needed
(`qdrant-client`, `asyncpg`) was already declared, from Phase 10.
**Generated:** 2026-08-27

## How Phase 15 was decided

Like Phase 14, this phase's identity was not given in the original
instruction. A first inspection pass (full Git history, all tags,
`docs/`, every `src/**/__init__.py` docstring, every
`tests/unit/*/test_dependency_boundaries.py`, and the recovered
pre-Phase-3 `docs/architecture.md`) found the same six
historically-named-but-unbuilt candidates Phase 14's own investigation
already surfaced (`bootstrap`, `runtime`, `plugins`, `api`, `cli`,
plus `infrastructure`/`scorers` as weaker, doc-only candidates), and
confirmed — across six independently-authored dependency-boundary
tests, Phases 9 through 14 — that exactly four names
(`bootstrap`, `plugins`, `api`, `cli`) are consistently and
repeatedly enforced in actual code as forbidden, not-yet-built
outer layers, with no ordering signal among them anywhere. That was
reported and left unresolved (**PHASE 15 BLOCKED — ARCHITECTURAL
CONTRACT MISSING**). Once told **Phase 15 = `bootstrap`**, a second
inspection pass (`core/protocols.py`'s `SupportsLifecycle`, every
storage/vector driver's own "caller responsibility" module docstring,
`pipeline/pipeline.py`'s own naming of `application`/`cli`/`bootstrap`
as sharing one gap, and every current usage of "dependency injection"/
"container"/"service locator" across `src/`) produced an 18-item
contract report. One point — whether Bootstrap needed its own
`start`/`stop` pair for a persistent lifecycle, versus two plain
functions relying on Pipeline's own existing per-run resource
release — was resolved by directly applying this phase's own "use the
smallest contract supported by the evidence" instruction rather than
guessed, and flagged as the one default the person could override.
Implementation began only after the contract was reviewed.

## What Bootstrap does

One module, `src/bootstrap/wiring.py`, exposing:

- **`build_repository_client(config) -> GitRepositoryClient`**,
  **`build_workspace_manager(config) -> FilesystemWorkspaceManager`**,
  **`build_collector(config) -> Collector`**,
  **`build_storage(config) -> StorageBundle`** (async — performs
  each backend's own connect/initialize-schema sequence),
  **`build_vector_store(config) -> VectorStore | None`** (async —
  constructs a real `AsyncQdrantClient`/`QdrantVectorStore` and calls
  `ensure_collection` only if `vector.enabled` is configured) — five
  independently callable, independently tested Port-construction
  functions, each reading its own slice of `core.config.AppConfig`.
- **`build_application(config=None, *, memory_store=None,
  extra_steps=()) -> Pipeline`** — constructs the concrete `Collector`
  and storage backend a configured flow needs, wraps them into three
  `Step`s (`collect`, `unpack_repositories`, `persist_repositories`)
  via `pipeline.steps.CallableStep`/`MapStep`, appends `extra_steps`,
  and calls `application.build_pipeline` with every closeable
  resource — never `Pipeline.run` itself.
- **`bootstrap(config=None, *, memory_store=None, extra_steps=(),
  context=None) -> PipelineResult`** — calls `build_application`, then
  `application.run_flow`.

All plain functions. No class, no container, no service locator, no
global registry — see "Design decisions," below.

## Scope of the default flow (deliberately narrow)

`build_application`'s own default flow collects `SourceRepository`
entities from one configured `source` and persists each one via the
configured storage backend's `SourceRepositoryStore`. It does not
clone a repository's contents, walk its files, parse, extract,
analyze, build a graph, or make a Foundation decision — each of those
is a genuine business choice (which of five parser languages, which
of seven extractor concerns, which of eight analyzer categories, in
what order) that nothing in the frozen architecture specifies, and
choosing one would be exactly the "business logic belonging to lower
layers" this phase's own brief forbids. `build_repository_client`/
`build_workspace_manager` are constructed and exposed as
independently callable, independently tested functions precisely so a
caller assembling a richer flow via `extra_steps` can wire repository
access the same way `build_application` wires collection/storage,
without this phase forcing a specific choice of what that richer flow
should be.

## Design decisions

**1. Plain functions, not a class/container.** Every current
"dependency injection" reference in the frozen codebase is explicitly
qualified as "constructor/function dependency injection"
(`pipeline/pipeline.py`, `application/runner.py`), and "no hidden
service locator or global registry" is stated as a rule three separate
times across Phase 13–14 code. "Container" appears exactly once in
current `src/`, as a hypothetical aside in `parsers/base.py`, never
built. This directly conflicts with the recovered, superseded
`docs/architecture.md`, which specified a concrete
`core.container.Container` class — that design was never carried into
the current, frozen rebuild, and was not used here.

**2. No `SupportsLifecycle` implementation, no `start`/`stop` pair, no
`runtime.py`.** `core/protocols.py`'s `SupportsLifecycle` is
explicitly earmarked for "the future `bootstrap` **and** `runtime`
packages," but nothing in the frozen codebase through Phase 14
implements it — zero usages outside its own definition — and "reverse
order" (its own docstring's shutdown behavior) appears exactly once in
the whole repository, in that docstring, with no code anywhere
exercising it. The only lifecycle behavior that actually exists and is
exercised anywhere is `pipeline.pipeline.Pipeline.run`'s own
`finally`-block release of every `SupportsAsyncClose` resource,
once, per run. Bootstrap supplies `SupportsAsyncClose`-shaped
resources into that already-existing mechanism (`_CallbackCloser`
adapts each backend's own connection-closing function; `QdrantVectorStore`
and a caller-supplied `MemoryStore` already implement it directly)
rather than inventing a second, parallel lifecycle mechanism.

**3. One error class.** `BootstrapError(VAOSError)`, raised only for
an unrecognized `storage.backend`/`collectors.backend` value, a
backend's own required configuration missing, or a `Collector`
reporting a failed collection (`CollectionResult.succeeded is False`)
for the flow's one configured `source` — translating that Port's own
"failure reported as data" convention into `pipeline`'s "failure
reported by raising" convention, the one seam genuinely new to this
layer. Every other lower-layer error (`ConfigurationError`,
`StorageConnectionError`, `QdrantOperationError`, `ValidationError`,
`StepExecutionError`) propagates unwrapped —
`test_a_lower_layers_own_validation_error_propagates_unwrapped`
proves this directly.

**4. No `MemoryStore` fabricated.** No concrete `MemoryStore`
implementation exists anywhere in the frozen codebase — only the
abstract Port, in `src/memory/base.py`. Per this phase's own
instruction, `build_application`/`bootstrap` accept an
already-constructed `memory_store: MemoryStore | None` from the
caller instead of constructing one, the same relationship `storage`
(Phase 10) held toward `vector` before Phase 11 existed.

## One documented, narrow accommodation in Bootstrap's own file (nothing frozen touched)

`mypy --strict` on `src/bootstrap/` initially failed with one
error: the real, installed `qdrant-client==1.9.2` `AsyncQdrantClient`
does not structurally satisfy `storage/qdrant/driver.py`'s own,
frozen `_QdrantClientLike` Protocol under strict structural typing —
specifically, `_QdrantClientLike.search`'s `query_vector: list[float]`
is narrower than the real client's actual, wider parameter type.
This is a **latent gap in a frozen Phase 10 file**, never exercised
there because Phase 10 never constructed a real client itself (its
own tests use fakes). It is not a genuine runtime incompatibility —
`list[float]` is itself a `Sequence[float]`, so a real
`AsyncQdrantClient` behaves correctly — and Bootstrap is the first
code in the repository to construct one. Per this phase's own
frozen-phase rule, `storage/qdrant/driver.py` was **not modified**.
Instead, a single, explicitly-commented `# type: ignore[arg-type]`
was added at the one call site in `src/bootstrap/wiring.py` — entirely
within this phase's own new file — with the comment naming the exact
frozen file/line responsible and the minimum change that would remove
the need for it (widening `_QdrantClientLike.search`'s `query_vector`
parameter type to `Sequence[float]`). Reported here rather than
applied silently.

## Boundary-test corrections (test-only; no Phase 1–14 production code touched)

Running the full-repository suite after implementation surfaced three
failures, all the same shape as Phase 14's own single correction:

- `tests/unit/pipeline/test_dependency_boundaries.py::
  test_no_other_layer_imports_pipeline` — already exempted
  `src/application` (Phase 14's own correction); now also exempts
  `src/bootstrap`, for the identical reason.
- `tests/unit/application/test_dependency_boundaries.py::
  test_no_other_layer_imports_application` — had no exemption; now
  exempts `src/bootstrap`, since Bootstrap's whole job is calling
  `application.build_pipeline`/`run_flow`.
- `tests/unit/storage/test_dependency_boundaries.py::
  test_nothing_outside_storage_imports_from_storage` — had no
  exemption; now exempts `src/bootstrap`, since Bootstrap is the
  first and only layer authorized to construct a concrete storage
  backend directly (`application` explicitly declined to).

Each was surfaced, reported, and **left unmodified pending explicit
authorization** before any correction was applied — no test was
patched silently. Each correction adds exactly one exemption clause
(mirroring the existing `_application_root` exemption pattern
Phase 14 already established in `pipeline`'s own test) plus a
docstring paragraph explaining why; no assertion's actual rule was
weakened, widened beyond `bootstrap`, or removed.

## What this layer does NOT do

No collection-target cloning, file walking, parsing, extraction,
analysis, graph assembly, foundation scoring, embedding, or vector
search logic of its own — every one of those stays its own
already-frozen layer's concern, invoked only through the Ports this
phase constructs. No `SupportsLifecycle` implementation, no
`start`/`stop` pair, no `runtime.py` — see design decision 2. No DI
container, service locator, global registry, singleton registry,
composition-root class, service classes, use-case classes, or CQRS
classes anywhere in `src/bootstrap`. No second configuration system —
every value is read through the existing `AppConfig.get` dotted-path
mechanism. No modification to any existing storage/vector driver, and
no second storage or vector abstraction. No fabricated `MemoryStore`
backend — see design decision 4. `Pipeline.run` is never called
directly — only through `application.run_flow`. `pyproject.toml` was
not touched. `api`, `cli`, and `plugins` were not touched, imported,
or constructed.

## Quality gates

`pytest tests/unit/bootstrap/ -v`: **35 passed**, 0 failed, 0
skipped.

`pytest -q` (full repository): **1227 passed**, 0 failed, 0 skipped
(1192 Phase 1–14 + 35 new Phase 15).

`mypy --strict src/bootstrap/ tests/unit/bootstrap/`: **7 source
files, 0 errors.**
`mypy --strict src/`: **110 source files, 0 errors** (one documented,
narrow `type: ignore[arg-type]` — see above).

`ruff check src/bootstrap/ tests/unit/bootstrap/`: **clean.**
`ruff check src/ tests/`: exactly the one pre-existing `UP046`
finding in frozen `src/domain/interfaces.py` that already predates
this phase (documented as pre-existing in `docs/ruff_report.txt`
since at least Phase 14, and confirmed present before any Phase 15
work began) — nothing new introduced here.

**Import-boundary scan:** every `src.bootstrap` module's import
*statements* verified via `ast` (not execution) against an explicit
allow-list of all fourteen Phase 1–14 packages and a forbid-list of
`api`/`cli`/`plugins`
(`tests/unit/bootstrap/test_dependency_boundaries.py`); a
whole-`src/`-tree scan confirms no Phase 1–14 module imports
`src.bootstrap` back.

**Circular-dependency scan:** all 110 modules under `src/` (all
fourteen frozen packages plus `bootstrap`) import successfully in a
single Python process, in dependency order, with no import errors.

**Frozen-phase integrity:** `git diff --stat -- src/` over the whole
session is **empty** — zero production-code files touched. `git
status`/`git diff --stat` show exactly three modified files, all
test-only dependency-boundary corrections (see above), plus two new,
untracked directories (`src/bootstrap/`, `tests/unit/bootstrap/`).
No other file — Phase 1–14's or otherwise — was created, modified, or
deleted.

**Verification environment:** this sandbox ships Python 3.12.3;
`pytest`, `pytest-asyncio`, `mypy`, `ruff`, and `pyproject.toml`'s own
pinned runtime dependencies (`asyncpg`, `qdrant-client`) were absent
and installed standalone into a local `.venv`, matching the
substitution already unremarked in every prior phase's own report.
`mypy --strict` ran with `pyproject.toml`'s own
`[tool.mypy] python_version = "3.13"` in effect; no 3.13-exclusive
syntax was used anywhere in this phase's code.

## Package contents added this phase

```
src/bootstrap/__init__.py
src/bootstrap/errors.py
src/bootstrap/wiring.py
tests/unit/bootstrap/__init__.py
tests/unit/bootstrap/test_imports.py
tests/unit/bootstrap/test_dependency_boundaries.py
tests/unit/bootstrap/test_wiring.py
```

Plus the three corrected Phase 1–14 test files:
`tests/unit/pipeline/test_dependency_boundaries.py`,
`tests/unit/application/test_dependency_boundaries.py`,
`tests/unit/storage/test_dependency_boundaries.py`.

---

**Phase 15 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`,
`src/graph`, `src/foundation`, `src/storage`, `src/vector`,
`src/memory`, `src/pipeline`, and `src/application` (all production
code) unmodified. Three frozen-phase test conflicts encountered and
reported before any fix was applied, per this task's own frozen-phase
rule; resolved only after explicit authorization, by correcting
exactly three already-frozen dependency-boundary test files, each
with one narrow, precedent-matching exemption clause. One latent
typing gap in a frozen Phase 10 file discovered and reported
explicitly, accommodated with a single documented `type: ignore` fully
contained in this phase's own new code rather than left unaddressed
or fixed silently. Four design decisions reported above rather than
left implicit (plain functions over a container; no `SupportsLifecycle`
implementation; one minimal error class; no fabricated `MemoryStore`).
No Git tag created, no commit made, phase not auto-frozen.**

**PHASE 15 READY FOR FREEZE**
