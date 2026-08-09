# VAOS Phase 6 — Extractors Layer Summary

**Scope:** `src/extractors/__init__.py`, plus one `base.py` per concern —
`architecture/`, `ast/`, `foundation/`, `imports/`, `interfaces/`,
`patterns/`, `symbols/` — exactly the seven-subpackage, contracts-only
structure specified for this phase.
**`src/core`, `src/domain`, `src/repository`, `src/collectors`, and
`src/parsers` were not modified.** `pyproject.toml` was not modified — no
new dependency was needed this phase.
**Generated:** 2026-08-09

## What this layer does

`extractors` answers one question: *what does a single already-parsed
file's structure mean, in a form later phases can reuse directly?* Given a
`parsers.base.ParseResult`, each of the seven `...Extractor` Ports in this
layer derives one specific kind of reusable semantic information from it.
None of them parses source code (that's `parsers`, already built), analyzes
quality, scores repositories, builds graphs, or selects foundations — all
five are explicitly out of scope per this phase's instructions, and are
later, not-yet-built phases' concerns.

Each subpackage's `base.py` is fully self-contained and defines exactly
one contract, following the same `ok`/`failed` outcome-DTO shape as
`parsers.base.ParseResult` and `collectors.base.CollectionResult`:

- **`architecture/base.py`** — `ArchitectureExtractor` (`extract(parse_result)
  -> ArchitectureExtractionResult`), deriving a file's `PackageUnit`: its
  package path (from `relative_path`'s directory segments), whether it is
  that package's own root marker (`is_package_root_marker`, recognizing
  `__init__.py`/`__init__.pyi`/`mod.rs`/`index.ts`), and its declared
  nested modules (carried through from `ParseResult.modules`).
- **`ast/base.py`** — `AstExtractor`, deriving `AstMetadata`: eleven
  non-negative structural counts (classes, functions, methods, imports,
  exports, symbols, modules, async functions, documented classes,
  documented functions, lines) — facts, not judgments; complexity/quality
  scoring stays out of scope.
- **`imports/base.py`** — `ImportExtractor`, deriving normalized
  `DependencyEdge` entries from a file's `ParsedImport` entries
  (target module, imported names, alias, internal/external
  classification). Assembling edges across many files into an actual
  dependency graph is explicitly left to the future `graph` phase.
- **`symbols/base.py`** — `SymbolExtractor`, deriving `ExtractedSymbol`
  entries scoped to exactly the three kinds this phase's instructions
  name — classes, functions (including methods), and constants — each
  carrying a `build_qualified_name`-formatted unambiguous name (e.g.
  `"a.py::Foo.bar"`). Deliberately narrower than `ParseResult.symbols`,
  which covers every construct kind a `Parser` reports.
- **`interfaces/base.py`** — `InterfaceExtractor`, deriving
  `ExtractedInterface` entries across every interface-shaped form
  `src.parsers` can produce: a language-native `interface`
  (TypeScript/Go), a Rust `trait` (both already reported as
  `SymbolKind.INTERFACE`/`SymbolKind.TRAIT` symbols), and a Python
  `ABC`/`typing.Protocol` subclass (reported as an ordinary `ParsedClass`,
  since `src.parsers` does not special-case Python's structural-typing
  conventions — a concrete implementation is expected to recognize it from
  `base_classes`/`decorators`, documented in-module).
- **`patterns/base.py`** — `PatternExtractor`, deriving `ExtractedPattern`
  entries: freeform-named, evidence-backed recognitions (e.g.
  `"factory_method"`) found among a file's classes and functions. Whether
  using a recognized pattern was the *right* choice is analysis, left to
  the future `analyzers` phase.
- **`foundation/base.py`** — `FoundationExtractor`, deriving
  `FoundationCandidate` entries: raw, observable reuse signals
  (`is_public`, `has_docstring`, freeform `signals`) for a file's classes
  and functions. Deliberately carries no numeric score field — combining
  signals into a score and *selecting* a foundation is the future
  `foundation` phase's job (a different, not-yet-built package from this
  subpackage of the same name), not this extraction step.

## Design decisions made within the frozen contract-only scope

Two calls were needed to satisfy every requirement in this phase's
instructions without redesigning anything upstream or downstream:

1. **"Common interface," read as per-concern, not cross-concern.** The
   requested tree has no shared top-level `src/extractors/base.py`, so
   "each extractor must have a common interface" was read the same way
   `parsers.base.Parser` already establishes the pattern for its five
   language implementations: each subpackage's `base.py` *is* the one
   common interface every future concrete implementation of that specific
   concern must satisfy — a single abstract method,
   `extract(parse_result: ParseResult) -> ...ExtractionResult`, identical
   in shape across all seven, even though no single class spans them.
2. **Per-file scope, not per-repository.** All seven contracts operate on
   one `ParseResult` at a time, mirroring `Parser.parse`'s own per-file
   granularity, rather than accepting a whole repository's worth of parse
   results. This was the reading most consistent with the instructions'
   explicit "do NOT ... create graphs" boundary — assembling many files'
   `PackageUnit`/`DependencyEdge` entries into an actual package tree or
   dependency graph is exactly graph-building, so it stays a later phase's
   job; each Port here only ever describes one file's own contribution to
   that future structure.

Each subpackage's `base.py` also defines its own small
`require_successful_parse` validator (rejecting a `parse_result` with
`succeeded=False` via `core.exceptions.ValidationError`) rather than
importing a shared one from a sibling package — the same choice
`parsers.base.require_relative_path` and `collectors.base.require_source`
already made independently of each other, so this continues an existing
pattern rather than introducing a new one. No extractor-specific exception
class was added: every raise in this layer is `core.exceptions.
ValidationError`, already sufficient for a caller-contract violation (an
unsuccessful `ParseResult` handed to `extract`), matching the same
reuse-over-invention principle `domain`, `collectors`, and `parsers` each
followed for their own checks.

## Counts

| Metric | Count |
|---|---|
| Extractors source files (`src/extractors/**/*.py`) | 15 |
| Extractors test files (`test_*.py`) | 7 |
| Extractors test functions (test cases after parametrization) | 88 (100) |
| **Total project test count (Core + Domain + Repository + Collectors + Parsers + Extractors)** | **439** |
| Total source files (`src/**/*.py`) | 49 |
| Total test files (`tests/**/*.py`) | 51 |
| `...Extractor` Ports defined this phase | 7 (`ArchitectureExtractor`, `AstExtractor`, `ImportExtractor`, `SymbolExtractor`, `InterfaceExtractor`, `PatternExtractor`, `FoundationExtractor`) |
| Public module-level symbols across `src/extractors/*/base.py` | 33 (7 Ports, 7 `...ExtractionResult` DTOs, 8 extracted-construct DTOs, 3 `StrEnum` classification types, 7 `require_successful_parse` helpers, 2 extra helpers — `is_package_root_marker`, `build_qualified_name`) |

## Verification (all steps)

1. **Import validation** — every file in `src/extractors/` and its 7
   subpackages import successfully under the project's `src.`-prefixed
   convention, individually verified via `importlib.import_module` for
   the package and all 7 `base` modules.
2. **AST/grep-level dependency validation** — every `import`/`from`
   statement in `src/extractors/**/*.py` was enumerated: every file
   imports only `src.core.exceptions`, `src.core.logging`, and
   `src.parsers.base` — nothing else (`src.domain` is allowed per this
   phase's instructions but no file here has a genuine need for it: every
   DTO field this layer needs is already re-exposed through
   `parsers.base`). No file imports any of the 14 explicitly forbidden
   packages (`collectors`, `repository`, `analyzers`, `graph`,
   `foundation`, `storage`, `memory`, `vector`, `pipeline`, `plugins`,
   `api`, `cli`, `application`, `bootstrap`), confirmed by an explicit
   negative grep across all 14 that found zero matches. (`src.extractors.
   foundation` — this phase's own subpackage — is unaffected: the
   forbidden entry is the distinct, not-yet-built `src.foundation`
   selection/scoring package the module docstring calls out by name.)
3. **Architecture boundary validation / package isolation** — confirmed no
   subpackage imports a sibling subpackage (e.g. `src.extractors.
   architecture` never imports from `src.extractors.symbols`) — all seven
   are independently self-contained aside from the shared parent
   package's docstring-only `__init__.py`.
4. **Circular dependency check** — package-level graph extends to
   `extractors → {core, parsers}` (domain allowed, unused). No cycles.
   Reverse-direction check confirmed `core`, `domain`, and `parsers` do
   not reference `extractors` anywhere (AST-level grep, zero hits).
5. **Unit tests** — 100/100 pass for this layer (439/439 for the whole
   project). Every contract's `test_base.py` covers: the Port cannot be
   instantiated directly (`TypeError` on the bare ABC); `...ExtractionResult.
   ok`/`.failed` build correctly and independently; every
   `__post_init__` invariant (error message required/forbidden per
   `succeeded`, payload required/forbidden per `succeeded`) is exercised
   in both directions; `require_successful_parse` passes a successful
   `ParseResult` through unchanged and raises `ValidationError` on a
   failed one; every DTO is confirmed frozen; and each contract's own
   extra helper (`is_package_root_marker`, `build_qualified_name`) is
   tested directly, including `AstMetadata`'s eleven-field negative-count
   parametrization and `InterfaceOrigin`'s three-member round-trip.
6. **mypy --strict** — clean on `src/core` + `src/domain` +
   `src/repository` + `src/collectors` + `src/parsers` + `src/extractors`
   (49 files) and on the full `tests` tree (51 files, informational),
   targeting `--python-version 3.13` per `pyproject.toml`.
7. **Ruff** — **fully clean within this phase's scope** (`src/extractors/`
   + `tests/unit/extractors/`). One finding remains project-wide (`UP046`
   on `Repository`'s `Generic[EntityT]` base in `src/domain/interfaces.py`)
   — pre-existing from Phase 2, already reviewed and accepted there, noted
   again untouched in the Phase 4 and Phase 5 audits, and left untouched
   here per this phase's explicit instruction not to modify `src/domain/`.
   See `ruff_report.txt` for both the full and scoped runs.

## A note on the Python version used to run verification

This sandboxed environment has Python 3.12.3 available (no 3.13
interpreter is installable here). `pytest_report.txt` and the
interpreter-dependent parts of `mypy_report.txt` reflect that. `mypy
--strict` was still run with `--python-version 3.13` (mypy's target
semantics are governed by this flag, independent of the interpreter
running mypy itself), matching `pyproject.toml`'s `[tool.mypy]
python_version = "3.13"`. No 3.13-exclusive syntax was used anywhere in
this phase's code. This same substitution was already present, unremarked,
in both Phase 4's and Phase 5's own `pytest_report.txt`, so it is not a
new deviation introduced here.

## Package contents added this phase

```
src/extractors/
├── __init__.py                        (package docstring only, no re-exports)
├── architecture/
│   ├── __init__.py
│   └── base.py       (ArchitectureExtractor, PackageUnit, ArchitectureExtractionResult)
├── ast/
│   ├── __init__.py
│   └── base.py         (AstExtractor, AstMetadata, AstExtractionResult)
├── imports/
│   ├── __init__.py
│   └── base.py           (ImportExtractor, DependencyEdge, ImportExtractionResult)
├── symbols/
│   ├── __init__.py
│   └── base.py             (SymbolExtractor, ExtractedSymbol(Kind), SymbolExtractionResult)
├── interfaces/
│   ├── __init__.py
│   └── base.py               (InterfaceExtractor, ExtractedInterface, InterfaceOrigin, ...)
├── patterns/
│   ├── __init__.py
│   └── base.py                 (PatternExtractor, ExtractedPattern, PatternExtractionResult)
└── foundation/
    ├── __init__.py
    └── base.py                   (FoundationExtractor, FoundationCandidate(Kind), ...)

tests/unit/extractors/
├── __init__.py
├── architecture/test_base.py    (15 tests)
├── ast/test_base.py               (13 test functions, 23 cases)
├── imports/test_base.py             (12 tests)
├── symbols/test_base.py               (12 tests)
├── interfaces/test_base.py              (12 test functions, 14 cases)
├── patterns/test_base.py                  (12 tests)
└── foundation/test_base.py                  (12 tests)

docs/
├── phase6_summary.md   (this file)
├── pytest_report.txt   (updated: now covers the full 439-test suite)
├── mypy_report.txt     (updated: now covers src/extractors + tests/unit/extractors)
└── ruff_report.txt     (updated: now covers src/extractors + tests/unit/extractors)
```

## Not implemented this phase

Every other package (`analyzers`, `graph`, `foundation` [the selection/
scoring package, not this phase's `extractors.foundation` subpackage],
`storage`, `memory`, `vector`, `pipeline`, `api`, `cli`, `plugins`,
`application`, `bootstrap`) — none were touched. No concrete
`...Extractor` implementation was written this phase, by design: this
phase's instructions ask for contracts only (`base.py` per concern), the
same scope every prior "Port-defining" phase (Collectors, Parsers)
observed before any concrete implementation followed. No file parses
source, scores quality, builds a graph, or selects a foundation anywhere
in this layer — see "What this layer does," above.

---

**Phase 6 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, and `src/parsers` unmodified. Next phase not started —
awaiting your instruction.**
