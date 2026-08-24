# VAOS Phase 13 — Pipeline Layer Summary

**Scope:** `src/pipeline/__init__.py`, `src/pipeline/context.py`,
`src/pipeline/base.py`, `src/pipeline/pipeline.py`,
`src/pipeline/steps.py` — exactly the flat target tree this phase's
own instructions suggested, confirmed against the repository as
source of truth (no different Pipeline structure was already defined
anywhere in it).
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`,
`src/foundation`, `src/storage`, `src/vector`, and `src/memory` were
not modified.** `pyproject.toml` was not modified — no new dependency
was needed.
**Generated:** 2026-08-24

## Repository inspected first; no contract gap found

Before writing any code, the repository was cloned fresh from
`https://github.com/mn1363/VAOS-Core` (`main`, commit `c276a13`,
"Phase 12: Memory layer implementation") and every layer this phase's
own brief named was inspected in full: `src/core` (`exceptions.py`,
`protocols.py`, `config.py`, `logging.py`, `utils.py`), `src/domain`
(`entities.py`, `interfaces.py`), `src/collectors/base.py`,
`src/repository/base.py`, `src/parsers/base.py`, all seven
`src/extractors/*/base.py` subpackages, all seven
`src/analyzers/*/base.py` subpackages, all four `src/graph/*/base.py`
subpackages, all five `src/foundation/*/base.py` subpackages,
`src/storage/base.py` (plus its `sqlite`/`postgres`/`qdrant` driver
shapes), `src/vector/base.py`, and `src/memory/base.py`. Existing test
conventions were also read in full (`tests/unit/memory/
test_dependency_boundaries.py`, `test_imports.py`, and a
representative `test_base.py`) so this phase's own tests would match
established structure and idiom exactly.

No required contract was missing. Every value Pipeline needed — the
`VAOSError`/`ValidationError`/`NotFoundError` hierarchy, `get_logger`,
`core.protocols.SupportsAsyncClose`'s shape — already existed in
`core`, exactly as every other layer had already used them. No
existing Domain entity needed modification, and no existing contract
was duplicated.

One scoping observation, not a blocker: this phase's own **PURPOSE**
section lists exactly nine layers Pipeline "may coordinate"
(collectors, parsers, extractors, analyzers, graph, foundation,
storage, vector, memory) and does not name `repository` among them,
even though `repository` *is* listed among the layers forbidden from
importing Pipeline back in the **DEPENDENCY RULE** section. Since
nothing in this phase's implementation required `repository`, it was
deliberately left out of Pipeline's allowed dependencies rather than
assumed — see "Design decisions," below, and the explicit
`test_pipeline_does_not_import_repository_anywhere` guard test. This
is a one-line change to reverse in a future phase if `repository`
access turns out to be wanted after all.

## Design decisions made, and why each one is the minimal, best-precedented choice

Five decisions were required rather than found ready-made. Each is
documented in its own module's docstring at the point it applies;
summarized here:

1. **Pipeline defines generic orchestration primitives, not one
   hardcoded flow wiring all nine coordinated layers together.** The
   brief's own PURPOSE section says Pipeline "may" coordinate
   collectors/parsers/.../memory — permissive language, not a mandate
   to hardcode one specific `build_analysis_pipeline(...)` — and its
   own DEPENDENCY INJECTION section says a `Pipeline` "must NOT
   instantiate collectors, parsers, analyzers, databases, ... unless
   an existing frozen contract explicitly requires a factory," which
   none does. `Pipeline`, `Step`, `CallableStep`, and `MapStep` are
   therefore entirely Port-agnostic: none of the four files imports a
   single concrete or abstract type from `collectors`/`parsers`/
   `extractors`/`analyzers`/`graph`/`foundation`/`storage`/`vector`/
   `memory`. Assembling one specific flow out of concrete,
   already-constructed Ports and these generic adapters is left to
   whichever caller wants one — most naturally a future,
   not-yet-built `application`/`cli`/`bootstrap` layer (already named
   as an outer, pipeline-depending layer in this phase's own
   dependency rule), or a test, as `test_integration.py` demonstrates.
2. **Failure is reported by raising `StepExecutionError`, not by a
   `PipelineResult` with `succeeded=False`.** Every per-item Port
   across the codebase (`CollectionResult`, `ParseResult`, every
   extractor/analyzer/graph/foundation result) reports failure as
   data, because a single call commonly represents a scan that may
   legitimately encounter many independent, non-exceptional failures.
   A `Pipeline` run is the opposite: a single, ordered, all-or-nothing
   execution, where one step's failure must abort every step after
   it — exactly the brief's own "failure propagation" and "do not
   silently swallow exceptions" requirements. `PipelineResult` is
   therefore only ever constructed after a fully successful run (its
   own `__post_init__` rejects a failed `StepOutcome` entry, so this
   invariant is enforced, not just documented), and `StepOutcome.
   failed()` is used only internally, to record the one failing step
   as structured detail on the `StepExecutionError` raised — matching
   `src.repository.base.GitCommandError`'s own raise-on-failure
   precedent rather than the per-item pattern.
3. **`PipelineContext` is a single, mutable, explicitly-addressed
   `dict[str, Any]`, not a typed dataclass with one field per
   coordinated layer.** A fixed set of typed fields would require
   `context.py` to import every layer Pipeline might ever coordinate,
   directly contradicting decision 1's Port-agnostic design. `get`/
   `require`/`set` keep every read and write explicit at the call
   site — "no hidden global state," per the brief — while
   `require`'s `NotFoundError` (reused from `core.exceptions`, not a
   new type) gives missing-key failures the same catchable shape every
   other VAOS layer's own lookups already have.
4. **Two generic `Step` adapters (`CallableStep`, `MapStep`) cover
   every coordination shape actually present in the frozen
   architecture, rather than one bespoke `Step` subclass per Port.**
   Across all nine coordinated layers there are exactly two calling
   shapes: a single call with N named inputs and one output
   (`Collector.collect`, `Parser.parse`, any single-file `Extractor.
   extract`/`Analyzer.analyze` call, a graph `Builder.build` call, any
   `foundation` Port call, every `Repository`/`Storage`/`Vector`/
   `Memory` Port method), and a per-item call applied across a
   sequence (running a per-file Port across every file a `Collector`
   found, before handing the collected results to a repository-wide
   graph or foundation Port). `CallableStep`/`MapStep` cover both
   generically via constructor-injected `func` plus named
   `input_keys`/`output_key`, so most `Pipeline` construction needs no
   bespoke subclass at all — writing one per Port (upwards of thirty)
   would have been both the opposite of "keep minimal" and a much
   larger surface for this layer to accidentally start reimplementing
   a Port's own logic in its own adapter code.
5. **Resource cleanup ("lifecycle where required") is scoped to
   closing already-injected `core.protocols.SupportsAsyncClose`
   resources after `run`, not a broader start/stop lifecycle.**
   `Storage`/`Vector`/`Memory` Ports already expose `aclose()`
   matching this exact Protocol; nothing in the frozen architecture
   defines or requires a `start()`/acquire-time lifecycle for anything
   Pipeline coordinates (`core.protocols.SupportsLifecycle` is
   explicitly reserved, in its own docstring, for the not-yet-built
   `bootstrap`/`runtime` layers). `Pipeline.__init__` accepts an
   optional `resources` sequence, closed in a `finally` block after
   every `run` call — success or failure — going no further, matching
   the brief's own "unless the existing repository already requires
   it" ceiling on speculative infrastructure.

One further, smaller decision: neither `CallableStep` nor `MapStep`
runs concurrently — `MapStep` iterates its input sequence strictly in
order, one call at a time. The brief asks for deterministic execution
and separately forbids speculative async infrastructure; concurrent
execution would buy throughput Pipeline itself has no requirement to
provide, at the cost of nondeterministic completion order for no
compensating benefit.

## What this layer does

`pipeline` answers one question: *what is the generic machinery
needed to run an ordered, dependency-injected sequence of steps
against one shared, explicit context, propagating results and
failures deterministically — independent of which concrete Ports a
particular flow happens to coordinate?*

- **`context.py` — `PipelineContext`** — a slotted dataclass wrapping
  `values: dict[str, Any]`, with `has`, `get`, `require` (raises
  `NotFoundError` on a missing key), `set` (raises `ValidationError`
  on a blank key), and `to_mapping` (an independent shallow copy).
- **`base.py`** — `Step(ABC)`: a `name` property and an `async def
  execute(context) -> context` method every concrete step implements.
  `StepOutcome` and `PipelineResult`: frozen, validated result DTOs
  following the same `ok()`/`failed()`-constructor shape established
  everywhere else, with the one deliberate difference explained in
  decision 2. `PipelineError(VAOSError)` and
  `StepExecutionError(PipelineError)`: this layer's own exception
  hierarchy, the latter carrying `pipeline`/`failed_step`/
  `completed_steps` in `details` while preserving the original
  exception as `__cause__`. `require_non_blank` and
  `require_unique_step_names`: shared validation helpers, matching
  every other layer's own `require_*` convention.
- **`pipeline.py` — `Pipeline`** — constructed from an ordered
  `Sequence[Step]` plus optional `resources: Sequence[
  SupportsAsyncClose]`, both dependency-injected, never constructed
  internally. `run(context=None)` executes every step strictly in
  order, propagates `context` between them, wraps and raises on the
  first failure (no later step runs), always closes `resources` in a
  `finally` block, and returns a `PipelineResult` once every step has
  succeeded. Reusable: a single instance's `run` may be called more
  than once, with independent contexts, producing independent,
  equally deterministic results.
- **`steps.py` — `CallableStep`, `MapStep`** — the two generic
  adapters covering every coordination shape described in decision 4
  above, described there in full.

## Tests

`tests/unit/pipeline/` (97 tests total, all passing):

- `test_context.py` (11 tests) — `get`/`has`/`require`/`set`
  behavior, blank-key rejection, `NotFoundError` on a missing key,
  independent-copy `to_mapping`, direct `values=` construction.
- `test_base.py` (20 tests) — `Step`'s abstractness; `StepOutcome`'s
  `ok`/`failed` constructors and consistency validation;
  `PipelineResult`'s field access, `step_count`/`step_names`, blank-
  name rejection, and rejection of a failed `StepOutcome` entry;
  `PipelineError`/`StepExecutionError`'s place in the shared `VAOSError`
  hierarchy and cause/details preservation; `require_non_blank`/
  `require_unique_step_names`.
- `test_steps.py` (18 tests) — `CallableStep`/`MapStep` with sync and
  async `func`, positional multi-input wiring, missing-key
  `NotFoundError`, unwrapped exception propagation, blank-argument
  validation, empty-sequence input, strict input-order preservation,
  and stopping at the first failing item.
- `test_pipeline.py` (23 tests) — construction validation (blank name,
  duplicate step names), ordered execution and context propagation,
  empty-pipeline behavior, result collection, failure propagation
  (wrapped `StepExecutionError` with pipeline/step identity and
  preserved `__cause__`, no step after the failing one runs),
  deterministic execution across repeated runs, dependency injection,
  lifecycle resource closing (including on failure), and reusability.
- `test_dependency_boundaries.py` (17 tests, `ast`-based, mirroring
  `tests/unit/memory/test_dependency_boundaries.py`'s own structure) —
  no forbidden-layer import, every `src.*` import allowed, an explicit
  `repository` guard (see the scoping observation above), a
  repo-wide scan confirming no other layer imports `src.pipeline`
  back, and an internal DAG check across this package's own four
  modules.
- `test_imports.py` (5 tests) — every `pipeline` module imports
  cleanly by execution.
- `test_integration.py` (3 tests) — `Pipeline`/`CallableStep`/
  `MapStep` genuinely coordinating hand-written fakes that subclass
  the *real*, frozen `Collector` and `Parser` ABCs (never mocks): a
  four-step collect → unpack → list-files → parse flow: a real Port's
  own `ValidationError` propagating through `MapStep`/`Pipeline.run`
  unchanged as a `StepExecutionError`'s `__cause__`; and a
  `SupportsAsyncClose`-satisfying resource being closed after `run`.
  Entirely offline, using only hand-written in-memory fakes — no
  GitHub, PostgreSQL, Qdrant, or network access anywhere.

## Architectural verification

1. **Pipeline imports** — `context.py` imports only `dataclasses`,
   `typing.Any` (stdlib) and `src.core.exceptions` (allowed). `base.py`
   additionally imports `abc`, `collections.abc.Sequence`
   (stdlib) and its own sibling `context.py`. `pipeline.py` additionally
   imports `src.core.logging`, `src.core.protocols.SupportsAsyncClose`
   (allowed) and its own sibling `base.py`/`context.py`. `steps.py`
   imports `collections.abc`, `typing` (stdlib) and its own sibling
   `base.py`/`context.py`. No file in `src/pipeline` imports
   `collectors`/`parsers`/`extractors`/`analyzers`/`graph`/
   `foundation`/`storage`/`vector`/`memory`/`repository`/`domain` at
   all — every one of those nine coordinated layers, plus `domain`, is
   an allowed-but-currently-unused dependency, the same
   allowed-but-unused relationship `src.foundation` already has to
   `src.graph`/`src.analyzers`. Confirmed both by manual `ast`-walk
   inspection and by `test_pipeline_module_imports_no_forbidden_layer`/
   `test_pipeline_module_imports_only_allowed_layers`.
2. **Pipeline → Core/Domain/{nine coordinated layers} boundaries** —
   confirmed by (1) and by
   `test_pipeline_module_imports_only_allowed_layers`.
3. **No Pipeline → Repository dependency** — confirmed by
   `test_pipeline_does_not_import_repository_anywhere` and by (1):
   `src.repository` appears nowhere in `src/pipeline`. See the
   scoping observation above for why this exclusion was chosen.
4. **No lower layer imports Pipeline** — confirmed by
   `test_no_other_layer_imports_pipeline`, which scans every `.py`
   file under `src/` outside `src/pipeline` itself and asserts none of
   them imports `src.pipeline`. (`tests/unit/memory/
   test_dependency_boundaries.py`'s own `_FORBIDDEN_PREFIXES` had
   already pre-emptively listed `src.pipeline` as forbidden for
   `memory`, confirming this direction was anticipated before this
   phase existed; `test_no_other_layer_imports_pipeline` checks it
   repository-wide rather than relying only on that one frozen file.)
5. **No circular dependencies** — confirmed by
   `TestInternalDependencyGraph` in `test_dependency_boundaries.py`,
   which resolves this package's own relative imports (`from .base
   import ...`) explicitly and confirms `context.py` depends on
   nothing internal, `base.py` depends only on `context.py`, and
   `pipeline.py`/`steps.py` each depend only on `base.py`/`context.py`,
   never on each other — a DAG, not a cycle.
6. **No duplicate contracts introduced** — confirmed by inspection:
   `Step`/`PipelineContext`/`PipelineResult`/`StepOutcome` are new
   names with no existing counterpart anywhere in the frozen
   architecture; every existing contract Pipeline's own tests exercise
   (`Collector`, `CollectionResult`, `Parser`, `ParseResult`,
   `FileMetadata`, `SourceRepository`, `core.protocols.
   SupportsAsyncClose`) is imported from its own frozen module, never
   redefined.
7. **Frozen Phase 1–12 files remain unchanged** — confirmed via
   `git status --porcelain` (only `src/pipeline/` and
   `tests/unit/pipeline/` reported, both untracked/new) and `git diff
   --exit-code` (exits 0: zero bytes changed in any tracked file).
   `pyproject.toml`, `configs/`, every existing `docs/phaseN_summary.md`
   (1–12), `docs/architecture_audit.md`, `docs/dependency_graph.md`,
   and every existing `tests/unit/*` directory other than the new
   `tests/unit/pipeline/`: empty diff throughout.

## Quality gates

`pytest`: 97 new tests, all passing; full repository suite (Phase
1–13 combined) at **1151 passing, 0 failing, 0 skipped**. Full output
in `docs/pytest_report.txt`.

`mypy --strict --python-version 3.13`: `src/pipeline` +
`tests/unit/pipeline` clean (13 source files, confirmed in isolation
before the whole-repository run below). Full repository: **224 source
files checked, 0 errors** — see "A note on the verification
environment," below, for a stale-cache false positive encountered and
resolved mid-verification. Full output in `docs/mypy_report.txt`.

`ruff check`: `src/pipeline` + `tests/unit/pipeline` clean. Full
repository shows exactly the one pre-existing `UP046` finding in
frozen `src/domain/interfaces.py` that already predates this phase
(documented as pre-existing in Phase 9's, Phase 11's, and Phase 12's
own summaries) — nothing new introduced here. Full output in
`docs/ruff_report.txt`.

## A note on the verification environment

This sandboxed environment started this session with `pytest`,
`pytest-asyncio`, `mypy`, `ruff`, and `pyproject.toml`'s own pinned
runtime dependencies (`asyncpg`, `qdrant-client`) all absent; they
were installed standalone before any verification was run and before
any Phase 13 code was written, matching the substitution already
unremarked in every prior phase's own report.

One transient discrepancy, caught and resolved during this phase's own
verification rather than left in the delivered report: an early
`mypy --strict` run in this same session (before this note was
written) reported 2 errors in `src/storage/postgres/driver.py` —
`import-not-found` for `asyncpg` plus a spuriously-`unused`
`# type: ignore[import-untyped]` comment on that same line — while
Phase 12's own `docs/mypy_report.txt` had reported zero errors against
that identical, unmodified line. Rather than document that gap as an
unresolved, pre-existing environment issue, it was investigated: the
cause was a stale `.mypy_cache` directory in this working copy,
left over from an intermediate point in this session before
`asyncpg`/`qdrant-client` were fully installed. Deleting `.mypy_cache`
and re-running `mypy --strict` from a clean cache reproduced Phase
12's own zero-error result exactly (confirmed twice: once in the
working directory, once independently in the extracted `vaos-phase13-
pipeline-final.zip` copy, which never had a `.mypy_cache` to begin
with and was clean on its very first run). `git diff --exit-code` on
`src/storage/postgres/driver.py` throughout confirms it was never
touched — the false positive was purely a stale local cache artifact
of this session, not a code issue, and not something this phase
introduced or needed to work around. `docs/mypy_report.txt` reflects
the correct, cache-cleared, zero-error result. This sandbox has Python
3.12.3 available, matching every prior phase's own already-documented
substitution; `mypy --strict` was run with `pyproject.toml`'s own
`[tool.mypy] python_version = "3.13"` in effect throughout. No
3.13-exclusive syntax was used anywhere in this phase's code.

## Package contents added this phase

```
src/pipeline/
├── __init__.py    (package docstring only, no re-exports)
├── context.py      (PipelineContext)
├── base.py         (Step, StepOutcome, PipelineResult, PipelineError,
│                     StepExecutionError, require_non_blank,
│                     require_unique_step_names)
├── pipeline.py      (Pipeline)
└── steps.py         (CallableStep, MapStep)

tests/unit/pipeline/
├── __init__.py
├── test_context.py                 (11 tests)
├── test_base.py                    (20 tests)
├── test_steps.py                   (18 tests)
├── test_pipeline.py                (23 tests)
├── test_dependency_boundaries.py   (17 tests)
├── test_imports.py                 (5 tests)
└── test_integration.py             (3 tests)
```

## What this layer does NOT do

No collection, parsing, extraction, analysis, graph assembly,
foundation scoring, or persistence logic was implemented or
reimplemented anywhere in `src/pipeline` — every one of those stays
exclusively its own already-frozen layer's concern, coordinated only
through constructor-injected `Step`s. No concrete `Collector`,
`Parser`, `Extractor`, `Analyzer`, graph `Builder`, `foundation` Port,
or `Repository`/`Storage`/`Vector`/`Memory` Port implementation was
constructed or imported anywhere in `src/pipeline` itself — see design
decision 1. No hardcoded, single, end-to-end analysis flow was
assembled — that scope is left to a future `application`/`cli`/
`bootstrap` layer. No distributed execution, retry, queue, worker,
scheduling, or concurrent-execution infrastructure was added — see the
smaller decision on `MapStep`'s strictly sequential iteration. No
`SupportsLifecycle` start/stop machinery was added — only
`SupportsAsyncClose`-based cleanup, see design decision 5.
`pyproject.toml` was not touched. Every other not-yet-built package
(`api`, `cli`, `plugins`, `application`, `bootstrap`) was not touched.

---

**Phase 13 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`,
`src/graph`, `src/foundation`, `src/storage`, `src/vector`, and
`src/memory` unmodified. No genuine contract gap encountered; five
design decisions (generic orchestration over one hardcoded flow;
raise-on-failure over a `succeeded=False` result; a single
explicitly-addressed `PipelineContext` over per-layer typed fields;
two generic `Step` adapters over one bespoke subclass per Port;
`SupportsAsyncClose`-scoped lifecycle over a broader start/stop one)
plus one ordering decision (`MapStep` strictly sequential, no
concurrency) reported above rather than left implicit, plus one
scoping observation (`repository` deliberately excluded from
Pipeline's allowed dependencies — the brief's own PURPOSE list omits
it) flagged rather than silently assumed either way. No Git tag
created, no commit made, phase not auto-frozen. Phase 14 not started —
awaiting your instruction.**

**PHASE 13 READY FOR FREEZE**
