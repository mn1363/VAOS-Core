# VAOS Phase 7 — Analyzers Layer Summary

**Scope:** `src/analyzers/__init__.py`, plus one `base.py` per concern —
`architecture/`, `complexity/`, `dependency/`, `documentation/`,
`metrics/`, `quality/`, `security/`, `tests/` — exactly the
eight-subpackage, contracts-only structure specified for this phase.
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, and `src/extractors` were not modified.** `pyproject.toml`
was not modified — no new dependency was needed this phase.
**Generated:** 2026-08-10

## What this layer does

`analyzers` answers one question: *what does a single file's
already-extracted information tell us, in a form later phases can reuse
directly?* Given one of `src.extractors`'s per-file `...ExtractionResult`
DTOs, each of the eight `...Analyzer` Ports in this layer turns it into
an analytical result. None of them parses source code, collects
repositories, extracts raw structures, modifies repositories, generates
graphs, selects foundations, or performs ranking — all seven are
explicitly out of scope per this phase's instructions, and are later,
not-yet-built phases' concerns.

Each subpackage's `base.py` is fully self-contained and defines exactly
one contract, following the same `ok`/`failed` outcome-DTO shape as
`extractors.architecture.base.ArchitectureExtractionResult` and its
six siblings:

- **`architecture/base.py`** — `ArchitectureAnalyzer`
  (`analyze(extraction_result: ArchitectureExtractionResult) ->
  ArchitectureAnalysisResult`), deriving an `ArchitectureAssessment`: a
  file's package depth (computed from `package_path`, not stored
  redundantly), whether it is its package's root marker, and its
  declared nested-module count — all carried through from the
  `PackageUnit` the extractor already produced.
- **`complexity/base.py`** — `ComplexityAnalyzer`, deriving
  `ComplexityMetrics`: complexity-*proxy* ratios (methods per class,
  lines per function, the async-function ratio) computed from
  `AstMetadata`'s raw counts via a shared `safe_ratio` helper that
  returns `0.0` rather than dividing by zero. Not true cyclomatic or
  cognitive complexity — `src.extractors` exposes no branch or
  control-flow data to derive that from, and this Port invents none.
- **`dependency/base.py`** — `DependencyAnalyzer`, deriving a
  `DependencyProfile`: a file's own internal/external import breakdown
  and its deduplicated, sorted external target modules
  (`summarize_external_targets`), from its normalized `DependencyEdge`
  entries. Assembling many files' profiles into an actual dependency
  graph stays the future `graph` phase's job.
- **`documentation/base.py`** — `DocumentationAnalyzer`, deriving
  `DocumentationCoverage`: class/function/overall documentation ratios
  from `AstMetadata`'s documented/total counts, via a shared
  `coverage_ratio` helper that treats an empty population (no classes,
  no functions) as vacuously fully covered (`1.0`, not `0.0`).
- **`metrics/base.py`** — `MetricsAnalyzer`, deriving
  `NormalizedCodeMetrics`: `AstMetadata`'s raw construct counts
  re-expressed as densities per 1000 lines of code (`per_kloc`), so
  files of different sizes become comparable. Deliberately a distinct
  concern from `complexity` (shape-proxy ratios) and `documentation`
  (coverage ratios) — this Port normalizes *volume*.
- **`quality/base.py`** — `QualityAnalyzer`, deriving a
  `QualityAssessment`: the documented-public-candidate ratio among a
  file's `FoundationCandidate` entries, plus zero or more
  `QualityIndicator` entries flagging specific candidates, each carrying
  a `domain.entities.FindingSeverity`. The first of three Ports this
  phase that *evaluates* rather than merely measures, per the task's own
  "Evaluate" wording for this concern.
- **`security/base.py`** — `SecurityAnalyzer`, deriving a
  `SecurityAssessment`: a file's external-dependency exposure surface
  (count and deduplicated, sorted target modules) from its
  `DependencyEdge` entries, plus zero or more `SecurityIndicator`
  entries. `src.extractors` exposes no vulnerability database, secret
  scanner, or taint-analysis data, so this Port evaluates only the
  exposure signal already available — not actual vulnerabilities.
- **`tests/base.py`** — `TestsAnalyzer`, deriving `TestEvidence`:
  whether a file is conventionally a test file (`is_test_file`, by path
  segment or filename convention) and how many test-shaped functions and
  classes it declares (`is_test_symbol_name`, by naming convention: a
  `test_`-prefixed function/method, a `Test`-prefixed class), plus zero
  or more `TestIndicator` entries. Structural evidence only — no
  upstream layer provides measured runtime coverage, so none is invented
  here.

## Design decisions made within the frozen contract-only scope

Three calls were needed to satisfy every requirement in this phase's
instructions without redesigning anything upstream or downstream:

1. **"Consistent, typed interface," read the same way Phase 6 read
   "common interface."** No shared top-level `src/analyzers/base.py` is
   in the requested tree, so each subpackage's `base.py` *is* the one
   contract every future concrete implementation of that specific
   concern must satisfy — a single abstract method,
   `analyze(extraction_result: ...) -> ...AnalysisResult`, identical in
   shape across all eight, even though no single class spans them (the
   exact precedent `extractors.base.Extractor` would have set had one
   existed — it doesn't, by the same design choice, one layer down).
2. **Per-file scope, not per-repository — continuing Phase 6's own
   reading.** All eight contracts operate on one `...ExtractionResult`
   at a time, mirroring every `...Extractor.extract`'s per-file
   granularity, even though several of this phase's own concern
   descriptions use words like "the repository" and
   "repository/code metrics." Phase 6's summary already worked through
   this exact tension for extractors and concluded per-file scope is
   the reading consistent with "do NOT ... create graphs"; the same
   boundary appears verbatim in this phase's instructions ("do NOT ...
   generate graphs ... select foundations ... perform ranking"), so it
   was read the same way here. Assembling many files' `...Analysis
   Result`s into a repository-wide rollup (a full dependency graph, an
   aggregate coverage percentage) is exactly that kind of cross-file
   assembly, so it stays a later, not-yet-scoped phase's job (`graph`,
   `pipeline`); each Port here only ever analyzes one file's own
   extracted information.
3. **`src.domain` used only where "evaluate" — not "analyze" or
   "produce" — is the task's own verb.** `FindingSeverity` from
   `domain.entities` is imported in exactly three of the eight
   subpackages — `quality`, `security`, and `tests` (the last for its
   explicitly named "test quality indicators" facet) — because those
   are the three concerns this phase's own responsibility list describes
   with an evaluative verb ("Evaluate measurable code-quality
   indicators," "Evaluate available security-related indicators," and
   "...test quality indicators..."), while the other five ("Analyze...,"
   "Produce...") stay purely descriptive/computational and have no
   organic need for a severity vocabulary. This mirrors Phase 6's own
   finding that `src.domain` was allowed but unused there — here it is
   allowed and used, but only where the task's own wording calls for
   judgment, not everywhere it was merely permitted.

One field-design correction was made during test-writing, not left in
the initial draft: `ArchitectureAssessment.package_depth` was first
written as a stored field validated for consistency against
`package_path`'s length in `__post_init__`; this made every construction
site (including in tests) responsible for keeping two representations
of the same fact in sync for no benefit, so it was changed to a
`@property` computed from `package_path` directly — the same choice
`domain.entities.AnalysisRun.duration_seconds` already makes for its own
derived field. It can no longer disagree with the data it is derived
from.

Each subpackage's `base.py` also defines its own small
`require_successful_extraction` validator (rejecting an
`...ExtractionResult` with `succeeded=False` via
`core.exceptions.ValidationError`) rather than importing a shared one
from a sibling subpackage — the same choice every one of the seven
`extractors.*.base` modules already made independently of each other in
Phase 6, so this continues an existing pattern rather than introducing a
new one. No analyzer-specific exception class was added: every raise in
this layer is `core.exceptions.ValidationError`, already sufficient for
a caller-contract violation (an unsuccessful `...ExtractionResult`
handed to `analyze`, or an out-of-range/inconsistent field on a result
DTO), matching the same reuse-over-invention principle `domain`,
`collectors`, `parsers`, and `extractors` each followed for their own
checks.

## Counts

| Metric | Count |
|---|---|
| Analyzers source files (`src/analyzers/**/*.py`) | 17 |
| Analyzers test files (`test_*.py`) | 8 |
| Analyzers test functions (test cases after parametrization) | 146 (157) |
| **Total project test count (Core + Domain + Repository + Collectors + Parsers + Extractors + Analyzers)** | **596** |
| Total source files (`src/**/*.py`) | 66 |
| Total test files (`tests/**/*.py`) | 68 |
| `...Analyzer` Ports defined this phase | 8 (`ArchitectureAnalyzer`, `ComplexityAnalyzer`, `DependencyAnalyzer`, `DocumentationAnalyzer`, `MetricsAnalyzer`, `QualityAnalyzer`, `SecurityAnalyzer`, `TestsAnalyzer`) |
| Public module-level symbols across `src/analyzers/*/base.py` | 41 (8 Ports, 8 `...AnalysisResult` DTOs, 8 primary assessment/metrics DTOs, 3 `...Indicator` DTOs, 8 `require_successful_extraction` helpers, 6 extra helpers — `safe_ratio`, `summarize_external_targets`, `coverage_ratio`, `per_kloc`, `is_test_file`, `is_test_symbol_name`) |

## Verification (all steps)

1. **Import validation** — every file in `src/analyzers/` and its 8
   subpackages import successfully under the project's `src.`-prefixed
   convention, individually verified via `importlib.import_module` for
   the package and all 8 `base` modules, then re-confirmed in a fresh
   interpreter alongside every subpackage's own `__init__.py` (17
   modules total).
2. **AST/grep-level dependency validation** — every `import`/`from`
   statement in `src/analyzers/**/*.py` was enumerated: every file
   imports only `src.core.exceptions`, `src.core.logging`,
   `src.domain.entities` (in `quality`, `security`, and `tests` only —
   see design decision 3 above), and exactly one `src.extractors.*.base`
   module — nothing else. No file imports any of the 14 explicitly
   forbidden packages (`collectors`, `repository`, `parsers`,
   `foundation`, `graph`, `storage`, `memory`, `vector`, `pipeline`,
   `plugins`, `api`, `cli`, `application`, `bootstrap`), confirmed by an
   explicit negative grep across all 14 that found zero matches.
   (`src.parsers` is forbidden to `analyzers` even though it was allowed
   to `extractors` one layer down — no file here imports it; the DTOs
   this layer needs are already fully re-exposed through
   `extractors.*.base` in primitive-typed fields, so the boundary costs
   nothing.)
3. **Architecture boundary validation / package isolation** — confirmed
   no subpackage imports a sibling subpackage (e.g. `src.analyzers.
   quality` never imports from `src.analyzers.security`) — all eight are
   independently self-contained aside from the shared parent package's
   docstring-only `__init__.py`, the same choice Phase 6 made for
   `extractors`.
4. **Circular dependency check** — package-level graph extends to
   `analyzers → {core, domain (partial), extractors}`. No cycles.
   Reverse-direction check confirmed `core`, `domain`, and `extractors`
   do not import `analyzers` anywhere (AST-level grep for actual `from
   src.analyzers`/`import src.analyzers` statements, zero hits; a small
   number of pre-existing docstring *mentions* of "the future
   `analyzers` phase" remain from Phase 6, unchanged, and are not
   imports).
5. **Frozen-phase integrity** — `git status` shows only new, untracked
   paths (`src/analyzers/`, `tests/unit/analyzers/`); `git diff
   origin/main --stat` against every previously tracked file is empty.
   No Phase 1–6 file was modified, confirmed by git itself rather than
   by inspection alone.
6. **Unit tests** — 157/157 pass for this layer (596/596 for the whole
   project). Every contract's `test_base.py` covers: the Port cannot be
   instantiated directly (`TypeError` on the bare ABC);
   `...AnalysisResult.ok`/`.failed` build correctly and independently;
   every `__post_init__` invariant (error message required/forbidden per
   `succeeded`, payload required/forbidden per `succeeded`) is exercised
   in both directions; `require_successful_extraction` passes a
   successful extraction result through unchanged and raises
   `ValidationError` on a failed one; every DTO is confirmed frozen; and
   each contract's own extra helper(s) are tested directly, including
   `DependencyProfile`/`SecurityAssessment`'s sorted-and-deduplicated
   `external_targets` invariant and `is_test_file`/
   `is_test_symbol_name`'s convention-matching table.
7. **mypy --strict** — clean on `src/core` + `src/domain` +
   `src/repository` + `src/collectors` + `src/parsers` +
   `src/extractors` + `src/analyzers` (65 files) and on the full `tests`
   tree (68 files, informational), targeting `--python-version 3.13` per
   `pyproject.toml`. Three `**kwargs`-unpacking parametrized tests
   (in `complexity`, `documentation`, and `metrics`) that mypy correctly
   flagged as unsound against DTOs with mixed `int`/`float` fields were
   rewritten as individual, explicitly-typed test functions rather than
   silenced with `# type: ignore`.
8. **Ruff** — **fully clean within this phase's scope** (`src/analyzers/`
   + `tests/unit/analyzers/`). One finding remains project-wide (`UP046`
   on `Repository`'s `Generic[EntityT]` base in
   `src/domain/interfaces.py`) — pre-existing from Phase 2, already
   reviewed and accepted there, noted again untouched in the Phase 4,
   Phase 5, and Phase 6 audits, and left untouched here per this phase's
   explicit instruction not to modify `src/domain/`. See
   `ruff_report.txt` for both the full and scoped runs.

## A note on the Python version used to run verification

This sandboxed environment has Python 3.12.3 available (no 3.13
interpreter is installable here; `pip install -e .` fails for exactly
this reason, same as in every prior phase). `pytest_report.txt` and the
interpreter-dependent parts of `mypy_report.txt` reflect that. `mypy
--strict` was still run with `--python-version 3.13` (mypy's target
semantics are governed by this flag, independent of the interpreter
running mypy itself), matching `pyproject.toml`'s `[tool.mypy]
python_version = "3.13"`. No 3.13-exclusive syntax was used anywhere in
this phase's code. This same substitution was already present, unremarked,
in Phase 4's, Phase 5's, and Phase 6's own `pytest_report.txt`, so it is
not a new deviation introduced here.

## Package contents added this phase

```
src/analyzers/
├── __init__.py                        (package docstring only, no re-exports)
├── architecture/
│   ├── __init__.py
│   └── base.py       (ArchitectureAnalyzer, ArchitectureAssessment, ArchitectureAnalysisResult)
├── complexity/
│   ├── __init__.py
│   └── base.py         (ComplexityAnalyzer, ComplexityMetrics, ComplexityAnalysisResult)
├── dependency/
│   ├── __init__.py
│   └── base.py           (DependencyAnalyzer, DependencyProfile, DependencyAnalysisResult)
├── documentation/
│   ├── __init__.py
│   └── base.py             (DocumentationAnalyzer, DocumentationCoverage, ...)
├── metrics/
│   ├── __init__.py
│   └── base.py               (MetricsAnalyzer, NormalizedCodeMetrics, MetricsAnalysisResult)
├── quality/
│   ├── __init__.py
│   └── base.py                 (QualityAnalyzer, QualityIndicator, QualityAssessment, ...)
├── security/
│   ├── __init__.py
│   └── base.py                   (SecurityAnalyzer, SecurityIndicator, SecurityAssessment, ...)
└── tests/
    ├── __init__.py
    └── base.py                     (TestsAnalyzer, TestIndicator, TestEvidence, ...)

tests/unit/analyzers/
├── __init__.py
├── architecture/test_base.py    (14 tests)
├── complexity/test_base.py        (20 test functions, 21 cases)
├── dependency/test_base.py          (19 tests)
├── documentation/test_base.py         (20 tests)
├── metrics/test_base.py                 (20 tests)
├── quality/test_base.py                   (18 tests)
├── security/test_base.py                    (18 tests)
└── tests/test_base.py                         (17 test functions, 27 cases)

docs/
├── phase7_summary.md   (this file)
├── pytest_report.txt   (updated: now covers the full 596-test suite)
├── mypy_report.txt     (updated: now covers src/analyzers + tests/unit/analyzers)
└── ruff_report.txt     (updated: now covers src/analyzers + tests/unit/analyzers)
```

## Not implemented this phase

Every other package (`graph`, `foundation` [the selection/scoring
package, not this phase's dependency on `extractors.foundation`],
`storage`, `memory`, `vector`, `pipeline`, `api`, `cli`, `plugins`,
`application`, `bootstrap`) — none were touched. No concrete
`...Analyzer` implementation was written this phase, by design: this
phase's instructions ask for a "consistent, typed interface" (contracts),
the same scope every prior "Port-defining" phase (Collectors, Parsers,
Extractors) observed before any concrete implementation followed. No
file parses source, collects repositories, extracts raw structures,
modifies repositories, generates graphs, selects foundations, or
performs ranking anywhere in this layer — see "What this layer does,"
above.

---

**Phase 7 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, and `src/extractors` unmodified. Next
phase not started — awaiting your instruction.**

**PHASE 7 READY FOR FREEZE**
