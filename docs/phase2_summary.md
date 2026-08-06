# VAOS Phase 2 — Domain Layer Summary

**Scope:** `src/domain/entities.py`, `src/domain/dtos.py`, `src/domain/interfaces.py`
(plus `src/domain/__init__.py`, required for the package to be importable).
**`src/core` was not modified** — verified by checksum before and after this phase,
and re-verified by checksum immediately before this final quality-gate pass.
**Generated:** 2026-08-05 (final quality-gate confirmation pass — no Python source
file was touched in producing this document or the reports alongside it; only
`docs/*.md`/`*.txt` were written).

## Counts

| Metric | Count |
|---|---|
| Domain source files (`src/domain/*.py`) | 4 (`__init__.py`, `entities.py`, `dtos.py`, `interfaces.py`) |
| Domain test files (`test_*.py`) | 3 |
| Domain test functions | 48 |
| **Total project test count (Core + Domain)** | **96** |
| Total source files (`src/**/*.py`) | 12 |
| Total test files (`tests/**/*.py`) | 14 |
| Public API symbols in `domain` (classes, methods, functions) | 41 |

## Tool status

| Tool | Command | Status |
|---|---|---|
| **ruff** | `ruff check src tests --line-length 100` | ⚠️ 1 finding (see note below) |
| **mypy** | `mypy src/core src/domain --strict` | ✅ **Success: no issues found in 11 source files** |
| **mypy** | `mypy tests --strict` (informational) | ✅ **Success: no issues found in 14 source files** |
| **pytest** | `pytest -v` | ✅ **96 passed, 0 failed, 0 errors, 0 skipped** |

**ruff note:** the one finding (`UP046`, on `Repository`'s `Generic[EntityT]` base)
is the same style opinion already reviewed and deliberately accepted during the
Phase 1 architecture-freeze audit — `Generic[T]` is kept over PEP 695
type-parameter syntax for broader readability. It is not a defect and nothing
was silently left broken; see `ruff_report.txt` for the full note.

Full raw output for each tool is in `ruff_report.txt`, `mypy_report.txt`, and
`pytest_report.txt` alongside this file.

## Dependency graph summary

- `entities.py` depends only on `core` (specifically `core.exceptions.ValidationError`,
  for state-transition and construction-time invariant checks) — the one
  dependency `domain` is allowed to have.
- `dtos.py` and `interfaces.py` each depend only on `entities.py` (same-layer,
  sibling-module references via relative imports).
- **No cycles.** **No boundary violations** — verified by an AST walk of every
  import statement in `src/domain/*.py` against the full set of other frozen
  top-level packages (none are imported).
- **Reverse-direction check:** `src/core` contains zero references to `domain`
  beyond two docstring mentions that explicitly *document* the boundary
  ("`core` is free of any dependency on `domain`...") — confirmed these are
  prose, not imports, before ruling the reverse-direction check clean.

Full graph and methodology in `dependency_graph.md`... *(carried over from
Phase 1; this phase's boundary/cycle results for `domain` are summarized
above and were produced with the same AST-based technique.)*

## Architecture verification

- **File set:** exactly the 3 requested files plus the required `__init__.py`
  — no `value_objects.py` or `events.py` (also listed in the frozen `domain/`
  tree) were created, since they were not requested for this phase; no other
  layer was touched.
- **Immutability:** DTOs (`dtos.py`) are frozen, slotted dataclasses — pure,
  immutable snapshots. Entities (`entities.py`) are deliberately **not**
  frozen — they have a real lifecycle (status transitions), so immutability
  would be inappropriate there; identity-based equality is used instead of
  frozen-value equality. This split is documented in both modules'
  docstrings.
- **Type hints & docstrings:** every class, method, and function across all
  3 files is fully annotated and documented (Google-style).
- **Business rules enforced in the domain layer itself** (Clean Architecture):
  `SourceRepository` (PENDING→COLLECTING→READY/FAILED),
  `AnalysisRun` (PENDING→RUNNING→COMPLETED/FAILED/CANCELLED), and
  construction-time validation on all four entities — every illegal
  transition or invalid value raises `core.exceptions.ValidationError`,
  reusing Core's hierarchy rather than inventing a parallel one.
- **Deliberate scope restraint:** `Finding.category` is a free-form `str`,
  not a fixed enum — the frozen `extractors/` and `analyzers/` subpackages
  list two different, overlapping-but-conflicting category taxonomies, and
  picking one now would be `domain` deciding something that belongs to
  those not-yet-built phases. By contrast, `SourceLanguage` and
  `RepositoryProvider` *are* enums, because `parsers/` and `collectors/`
  each have exactly one, unambiguous, non-conflicting frozen subpackage
  list to mirror.
- **Naming collision resolved deliberately:** the persistence Port for
  `SourceRepository` is named `SourceRepositoryStore`, not
  `SourceRepositoryRepository` — avoiding a stutter caused by the entity's
  own name already containing "repository". The other three Ports keep the
  standard `XRepository` suffix. Documented inline in `interfaces.py`.
- **Public API test coverage:** 41/41 public symbols in `domain` are
  directly referenced by the test suite (verified by the same AST-based
  cross-check used in the Phase 1 audit).

## Real issues found and fixed during this phase

Two genuine Python/mypy gotchas were found and fixed while writing the tests
(not left as caveats):

1. A test stub class defined a method literally named `list` (implementing
   the abstract `Repository.list()` Port method) *before* another method in
   the same class body whose return annotation was `list[X]` — the name
   `list` was shadowed by the just-defined method within that class body,
   raising `TypeError: 'function' object is not subscriptable` at collection
   time. **Fixed at the root cause**: reordered each stub class so the
   entity-specific extra method is defined before its `list` override,
   rather than papering over it with `from __future__ import annotations`.
2. Two tests asserted `entity.status is X` twice, with a status-mutating
   method call in between; mypy's flow analysis does not know that a method
   call can change an attribute it already narrowed, so it flagged the
   second assertion as an "impossible" comparison
   (`comparison-overlap`) — a real, well-known mypy limitation, not a bug in
   the domain code. **Fixed** by capturing each post-mutation observation
   into its own freshly-named local variable before asserting, which is the
   standard idiom for this exact pattern.

## Package contents added this phase

```
src/domain/
├── __init__.py
├── entities.py      (5 entities/enums: Entity, SourceRepository, SourceFile,
│                      AnalysisRun, Finding + their status/provider/language enums)
├── dtos.py           (4 frozen DTOs, each with a from_entity() classmethod)
└── interfaces.py     (generic Repository[T] Port + 4 entity-specific Ports)

tests/unit/domain/
├── __init__.py
├── test_entities.py    (30 tests)
├── test_dtos.py         (8 tests)
└── test_interfaces.py   (10 tests)

docs/
├── phase2_summary.md   (this file)
├── pytest_report.txt
├── mypy_report.txt
└── ruff_report.txt
```

## Not implemented this phase

`src/domain/value_objects.py` and `src/domain/events.py` (both listed in the
frozen `domain/` tree, but not requested for Phase 2), and every other
package (`application`, `repository`, `storage`, `bootstrap`, `collectors`,
`parsers`, `extractors`, `analyzers`, `graph`, `scorers`, `foundation`,
`pipeline`, `api`, `cli`, `plugins`, `runtime`).

---

**Phase 2 complete. `src/core` unmodified. Repository layer (Phase 3) not
started — awaiting your instruction.**
