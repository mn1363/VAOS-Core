# VAOS Phase 14 — Application Layer Summary

**Scope:** `src/application/__init__.py`, `src/application/runner.py`
— the two-file, "bare functions" contract explicitly decided this
phase — plus one authorized, test-only correction to
`tests/unit/pipeline/test_dependency_boundaries.py` (a Phase 13 file;
no Phase 13 *production* code was touched).
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`,
`src/foundation`, `src/storage`, `src/vector`, `src/memory`, and
`src/pipeline` were not modified.** `pyproject.toml` was not
modified — no new dependency was needed.
**Generated:** 2026-08-25

## How Phase 14 was decided

Unlike Phases 1–13, this phase's identity was not given in the
original instruction — inspection of the cloned repository (`main`,
commit `1632611`, "Phase 13: Pipeline layer implementation"), every
phase summary, and the recovered pre-Phase-3 `docs/architecture.md`
found six historically-named-but-unbuilt candidates (`application`,
`bootstrap`, `runtime`, `plugins`, `api`, `cli`), no phase-to-name
mapping for any of them, and the one document that might have
resolved it (`BOOTSTRAP_ORDER.md`, named in Phase 1's own plan) never
created in any commit. That was reported and left unresolved. Once
told **Phase 14 = `application`**, a second inspection pass (all
thirteen `src/*` `__init__.py`/`base.py` docstrings, `test_pipeline.py`
family tests, `docs/phase*_summary.md`) produced a 13-item contract
report; two items — the exact public interface and whether Application
should be structured as services, use-cases, commands/queries, or bare
functions — were not resolvable from project evidence and were left
`UNDEFINED — REQUIRES ARCHITECTURAL DECISION` rather than invented.
**Bare functions** was then explicitly chosen. Implementation began
only after that choice was made.

## What Application does

Two plain functions in `src/application/runner.py`:

- **`build_pipeline(name, steps, *, resources=())  -> Pipeline`** —
  assembles an already-constructed sequence of `Step`s and resources
  into a `Pipeline`. A one-line call to `Pipeline.__init__`.
- **`run_flow(pipeline, context=None)  -> PipelineResult`** — executes
  an already-constructed `Pipeline` and returns its typed result. A
  one-line call to `Pipeline.run`.

Both are deliberately this thin. `src.pipeline.pipeline`'s own module
docstring states that assembling one *specific* flow — which `Step`s,
wired to which concrete, already-constructed
`Collector`/`Parser`/`Extractor`/`Analyzer`/graph
`Builder`/`foundation` Port/`Repository`/`Storage`/`Vector`/`Memory`
Port — is a business-flow decision no frozen phase through Phase 13
makes, and hardcoding one here would mean inventing an unevidenced
flow, directly against this phase's own "do not create speculative
abstractions" instruction. `tests/unit/pipeline/test_integration.py`
already establishes the precedent for *how* a caller builds the
`Step`s a flow needs — `CallableStep`/`MapStep` directly around
already-constructed Port instances — and this phase does not
reimplement that; it supplies only the two actions no frozen layer
performed yet: constructing a `Pipeline`, and executing one.

## Design decisions

**1. Two functions, not one.** "Construct the Pipeline" and "execute
the Pipeline" were kept as two separate functions rather than one
combined call, because `Pipeline` is explicitly documented as
reusable ("a single `Pipeline` instance is reusable... calling `run`
more than once, with independent contexts, produces independent,
equally deterministic results") — a single one-shot function would
silently discard that. `TestReusability` in `test_runner.py` exercises
this directly: one `build_pipeline` call, two independent `run_flow`
calls.

**2. No `ApplicationError` exception class.** `core.exceptions`'s own
docstring states each layer defines its own `VAOSError` subclass only
for a failure mode genuinely new to that layer — matching
`Pipeline.__init__`'s own precedent of raising the plain, inherited
`ValidationError` for basic argument checks, and reserving
`PipelineError`/`StepExecutionError` for the one failure concept
Pipeline itself introduces. `build_pipeline`/`run_flow` introduce no
new failure mode — both propagate exactly what `Pipeline.__init__`/
`Pipeline.run` already raise — so no new exception type was added.

**3. No import of `collectors`/`parsers`/`extractors`/`analyzers`/
`graph`/`foundation`/`storage`/`vector`/`memory`/`repository`.**
Although this phase's instruction allows Application to depend on any
Phase 1–13 layer "where required by the actual architecture," neither
function's minimal, generic contract *requires* any of them — the
concrete Port instances a real flow would use are supplied by the
caller when it builds `Step`s, exactly as `test_integration.py`
demonstrates, not constructed or imported inside `src/application`
itself. `tests/unit/application/test_integration.py` proves this
generic contract genuinely coordinates real `Collector`/`Parser` Ports
end-to-end without `src/application` importing either.

## Boundary-test correction (test-only; no Phase 13 production code touched)

Running the full-repository suite after implementation surfaced one
failure: `tests/unit/pipeline/test_dependency_boundaries.py::
test_no_other_layer_imports_pipeline`, a Phase 13 test, failed because
`src/application/runner.py` imports `src.pipeline` — exactly what
this phase's own contract requires ("construct the Pipeline, execute
the Pipeline... use the actual frozen Pipeline interfaces").

That test's own docstring stated its intent as "the dependency
direction must remain one-way," but its implementation checked,
unconditionally, that *no* file outside `src/pipeline/` imports
`src.pipeline` — correct at the moment Phase 13 was written, since
every layer that existed then (`core` through `memory`) genuinely was
a lower layer barred from importing pipeline, but with no exception
for an outer layer this same module's own docstring had already
anticipated ("a future, not-yet-built `application`/`cli`/`bootstrap`
layer").

Per this phase's explicit authorization, exactly one file was
corrected: `tests/unit/pipeline/test_dependency_boundaries.py`. No
`src/` file — Phase 13's or any other phase's — was touched; confirmed
by `git diff --stat -- src/` (empty) and a full SHA-256 comparison
against a pre-Phase-14 hash of every `src/`+`tests/` file (see
"Quality gates," below). The correction:

- `test_no_other_layer_imports_pipeline` now also exempts
  `src/application`, alongside `src/pipeline` itself, with its
  docstring updated to explain why.
- **New:** `test_only_lower_layers_are_barred_from_importing_pipeline`
  — the same rule re-stated explicitly, parametrized over all twelve
  lower layers by name (`core`, `domain`, `repository`, `collectors`,
  `parsers`, `extractors`, `analyzers`, `graph`, `foundation`,
  `storage`, `vector`, `memory`), so a future regression names the
  exact offending layer.
- **New:** `test_application_is_the_authorized_outer_consumer_of_pipeline`
  — the positive counterpart, proving `src.application` genuinely
  does import `src.pipeline` rather than merely being unforbidden
  from doing so.

This is a correction to what a Phase 13 *test* checks, made because
an explicitly authorized outer layer now exists that the test
predates — not a change to Phase 13's dependency rule, architecture,
or production code, none of which was touched.

## What this layer does NOT do

No collection, parsing, extraction, analysis, graph assembly,
foundation scoring, persistence, embedding, vector search, or git
access — every one of those stays exclusively its own already-frozen
layer's concern. No `Collector`, `Parser`, `Extractor`, `Analyzer`,
graph `Builder`, `foundation` Port, or
`Repository`/`Storage`/`Vector`/`Memory` Port was constructed or
imported anywhere in `src/application`. No service classes, use-case
classes, or command/query hierarchy — two plain functions only, per
this phase's explicit instruction. No `SupportsLifecycle` start/stop
machinery — that Protocol is explicitly reserved, in frozen
`core/protocols.py`'s own docstring, for "the future
`bootstrap`/`runtime` packages," not Application. No new exception
type — see design decision 2. No global state, module-level
singleton, or service locator anywhere in `src/application`. No
hardcoded, specific, end-to-end analysis flow — that remains a future
caller's decision, not this layer's. `pyproject.toml` was not
touched. Every other not-yet-built package (`api`, `cli`, `plugins`,
`bootstrap`, and — inconsistently named across Phase 1–13's own
history — `runtime`) was not touched.

## Quality gates

`pytest`: 41 new tests (28 in `tests/unit/application/`; 13 from the
boundary-test correction — 12 parametrized per-layer checks plus one
positive check), all passing. Full repository suite (Phase 1–14
combined) at **1192 passing, 0 failing, 0 skipped**. Full output in
`docs/pytest_report.txt`.

`mypy --strict --python-version 3.13`: `src/application` +
`tests/unit/application` clean in isolation (7 source files). Full
repository: **231 source files checked, 0 errors** (224 Phase 1–13 +
7 new Phase 14). Full output in `docs/mypy_report.txt`.

`ruff check`: `src/application` + `tests/unit/application` fully
clean. Full repository shows exactly the one pre-existing `UP046`
finding in frozen `src/domain/interfaces.py` that already predates
this phase (documented as pre-existing in Phases 9, 11, 12, and 13's
own summaries) — nothing new introduced here. Full output in
`docs/ruff_report.txt`.

**Frozen-source integrity:** a SHA-256 hash of every `src/`+`tests/`
`.py` file was taken before any Phase 14 work began, then re-taken
after. `diff` between the two shows exactly one line changed —
`tests/unit/pipeline/test_dependency_boundaries.py`, the one
authorized correction — and every other one of the 223 other Phase
1–13 files byte-for-byte identical. `git diff --stat -- src/` over
the whole session shows zero changes to any `src/` file.

**Circular-dependency check:** every one of the 107 modules under
`src/` (all thirteen frozen packages plus `application`) imports
successfully in a single Python process, in dependency order, with no
import errors.

**Verification environment:** this sandbox ships Python 3.12.3 and
started this session with `pytest`, `pytest-asyncio`, `mypy`, `ruff`,
and `pyproject.toml`'s own pinned runtime dependencies (`asyncpg`,
`qdrant-client`) all absent; installed standalone before any
verification was run, matching the substitution already unremarked in
every prior phase's own report. `mypy --strict` was run with
`pyproject.toml`'s own `[tool.mypy] python_version = "3.13"` in
effect; no 3.13-exclusive syntax was used anywhere in this phase's
code. `.mypy_cache`/`.pytest_cache`/`.ruff_cache` were cleared before
the final verification run reflected in the reports above.

## Package contents added this phase

```
src/application/__init__.py
src/application/runner.py
tests/unit/application/__init__.py
tests/unit/application/test_runner.py
tests/unit/application/test_integration.py
tests/unit/application/test_dependency_boundaries.py
tests/unit/application/test_imports.py
```

Plus the one corrected Phase 13 file:
`tests/unit/pipeline/test_dependency_boundaries.py`.

---

**Phase 14 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`,
`src/graph`, `src/foundation`, `src/storage`, `src/vector`,
`src/memory`, and `src/pipeline` (all production code) unmodified.
One frozen-phase conflict encountered and reported before any fix was
applied, per this task's own frozen-phase rule; resolved only after
explicit authorization, by correcting exactly one Phase 13 *test*
file, with two new tests added to make the corrected rule explicit
and its positive direction proven, not merely assumed. Three design
decisions reported above rather than left implicit (two-function
split for reusability; no new exception type; no import of any
domain-specific lower layer). No Git tag created, no commit made,
phase not auto-frozen.**

**PHASE 14 READY FOR FREEZE**
