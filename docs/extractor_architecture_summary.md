# Concrete Extractor Summary: `StructuralArchitectureExtractor`

Not a numbered phase. An additive concrete implementation of the already-frozen Phase 6
`ArchitectureExtractor` Port, approved and scoped by the Architecture Extractor Contract
Discovery report this implements (third concrete extractor, after `imports` and `ast`/`symbols`).

## Responsibility

`StructuralArchitectureExtractor` (`src/extractors/architecture/structural.py`) turns one
file's already-parsed `ParseResult` and its own `relative_path` into a single `PackageUnit` —
where the file sits in its repository's package/module structure. It performs no naming-
convention inference, no Go-specific package-root invention, no cross-file aggregation, and no
judgment about whether that structure is well-designed; assembling many files' units into a
repository-wide package tree remains an explicitly out-of-scope, not-yet-built `graph` concern,
and judging structure quality remains an `analyzers` concern.

## Contract

- Zero-argument, stateless: no `__init__` override, exactly like `StructuralImportExtractor`,
  `StructuralAstExtractor`, and `StructuralSymbolExtractor`.
- `extract(self, parse_result: ParseResult) -> ArchitectureExtractionResult` — identical
  signature to the abstract method it implements.
- First action: `require_successful_parse(parse_result)`, the already-existing, already-tested
  helper from `base.py`.
- One implementation, five languages: the same instance handles `ParseResult`s from every one
  of `PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, and `CppParser`, since
  `package_path`/`is_package_root` are derived from `relative_path` alone (language-independent)
  and `declared_modules` is copied from `parse_result.modules`, which each parser already
  normalizes into the same `ParsedModule` shape. Verified directly
  (`test_go_file_carries_its_declared_package_module`,
  `test_declared_modules_preserves_source_order`, and the per-marker-language cases), not
  merely assumed from the contract.

## Field mapping

| `PackageUnit` field | Source |
|---|---|
| `relative_path` | `parse_result.relative_path` |
| `package_path` | directory portion of `parse_result.relative_path`, split on `/`, as a tuple |
| `is_package_root` | `is_package_root_marker(parse_result.relative_path)` |
| `declared_modules` | `parse_result.modules`, verbatim |

## `package_path` derivation

A pure string operation over `relative_path` alone, with no re-parsing of source content: if
`relative_path` contains no `/`, `package_path` is `()` (a root-level file); otherwise it is the
directory portion — everything before the final `/` — split on `/` into a tuple of segments.
`src/extractors/architecture/base.py` → `("src", "extractors", "architecture")`. No language-
specific package-declaration syntax (Go's `package` clause, Rust's `mod`, a Python namespace
package) is consulted; `package_path` reflects the file's location on disk, not any declaration
inside it.

## `is_package_root` — existing marker behavior, unchanged

Delegates entirely to the already-frozen `is_package_root_marker`, which matches a file's own
name (the final `/`-separated segment) against exactly four conventional marker filenames:
`__init__.py`, `__init__.pyi`, `mod.rs`, `index.ts`. This implementation adds no new marker, no
new matching logic, and no per-language special case — it calls the existing helper and uses
its return value exactly as given.

### Go marker limitation (explicitly not solved here)

`_PACKAGE_ROOT_MARKERS` has no Go entry: Go has no single conventional root-marker filename the
way Python (`__init__.py`) or Rust (`mod.rs`) do — every file in a Go package directory
independently declares the same `package` clause, so no one filename is privileged as "the"
root marker. `StructuralArchitectureExtractor` does not invent one. A Go file's
`is_package_root` is therefore always `False` under the current, frozen `base.py` contract,
regardless of its `package` clause — verified explicitly
(`test_go_file_carries_its_declared_package_module` asserts `is_package_root is False` for a
real `package widget` file). This is a known, accepted scope gap in the frozen contract itself,
not a defect introduced by this implementation; extending `_PACKAGE_ROOT_MARKERS` or adding
Go-specific logic would be a `base.py` contract change, which is out of scope.

## `declared_modules` — pass-through, not resolution

Copied verbatim from `parse_result.modules`: same order, same objects, no deduplication, no
filtering, matching the pass-through precedent set by `StructuralImportExtractor` and
`StructuralSymbolExtractor`. Verified with a real Rust file declaring three `mod` blocks in a
deliberately non-alphabetical order (`zeta`, `alpha`, `middle`), asserting the output order
matches that exact sequence.

### Python empty-module behavior (existing parser behavior, preserved)

`PythonParser` never produces a `ParsedModule` — Python has no nested module/namespace
declaration construct the other four languages have (Rust `mod`, Go `package`, TypeScript
`namespace`, C++ `namespace`). Every real Python `ParseResult` therefore has `modules == ()`,
and `declared_modules` is correspondingly always `()` for Python files — verified explicitly
(`test_python_file_has_no_declared_modules` asserts `parse_result.modules == ()` on real
`PythonParser` output before asserting the same on the extracted unit). This is existing,
frozen parser behavior, not something this extractor compensates for or should compensate for.

## No cross-file analysis

Every `PackageUnit` is derived from exactly one `ParseResult` in isolation. Nothing here reads
sibling files, resolves a package's full member list, or builds any tree/graph structure across
files — that is the future, not-yet-built `graph` phase's job, per `ArchitectureExtractor`'s own
`base.py` docstring.

## Failure behavior

Exactly one error path: a failed input `ParseResult` causes `require_successful_parse` to raise
`ValidationError` immediately, uncaught, unchanged from its existing behavior. No new exception
type was introduced. `ArchitectureExtractionResult.failed(...)` is never constructed by this
implementation — once given a successful `ParseResult`, the field-by-field mapping above is
total; there is no partial-failure case for this concern to express as data.

## Tests

`tests/unit/extractors/architecture/test_base.py` — pre-existing, unchanged, still passing.

`tests/unit/extractors/architecture/test_structural.py` — 14 new tests, one per required case
from the locked contract: root-level file (`package_path == ()`), nested path (full directory
segments), Python `__init__.py`, Python `__init__.pyi`, Rust `mod.rs`, TypeScript `index.ts`
(each a real package-root marker via its real parser), an ordinary non-root file, a real Go file
with a real parsed `package` clause, a real Python file with empty `modules`, an "empty"
successful `ParseResult` (a file with no content, every parsed-content field at its default),
the `ValidationError` failure path, exact `PackageUnit` field mapping asserted together in one
test, `declared_modules` source-order preservation across three deliberately out-of-order `mod`
declarations, and an `isinstance` check against the `ArchitectureExtractor` Port itself. Every
language case parses a real source snippet with the real parser — no hand-built `ParsedModule`
stands in for parser output.

## Integration test

`tests/integration/test_architecture_extraction.py` — new, self-contained (its own local
`_config`, `_clone_repository_func`, `_enumerate_files`, `_parse_files_func`, `_run_git`; does
not import from `tests/integration/test_reference_flow.py`, matching this repository's
convention of self-contained test modules). Creates one real local git repository under
`tmp_path` with `pkg/widget.py` (nested, non-root), `pkg/__init__.py` (nested package-root
marker), and `helpers.go` (root-level, with a real `package main` clause), runs the Reference
Flow's existing three steps plus one new `extract_architecture` `MapStep`
(`input_key="parse_results"`, `output_key="architecture_results"`,
`func=StructuralArchitectureExtractor().extract`) through `bootstrap(config,
extra_steps=[...])`, and asserts the real resulting `PackageUnit` data for all three files —
including the Go file's `package_path == ()`, `is_package_root is False`, and one declared
module named `"main"`. Requires the real `git` executable; skipped, not failed, when
unavailable.

## Verification results

Run against this checkout (`HEAD` = `7bfcdfd`), Python 3.12.3 (the pinned `requires-python =
">=3.13"` interpreter was not available in this environment; only the interpreter used to *run*
the tests differs from the pinned version — no language feature used here is version-sensitive
between 3.12 and 3.13):

- `pytest tests/unit/extractors/architecture/test_structural.py` — **14 passed**.
- `pytest tests/integration/test_architecture_extraction.py` — **1 passed**.
- `pytest` (full suite) — **1377 passed**, 0 failed, the same 2 pre-existing, unrelated
  deprecation warnings as before this work (`starlette`/`httpx`). 1362 (verified baseline before
  this implementation, by temporarily stashing the new files and re-running) + 14 + 1 = 1377.
- `mypy --strict src/` — Success: no issues found in **125** source files (124 before this
  implementation, +1 for `structural.py`).
- `ruff check src/ tests/` — exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py`; zero new findings.

## Changed files

New files only:

```
src/extractors/architecture/structural.py
tests/unit/extractors/architecture/test_structural.py
tests/integration/test_architecture_extraction.py
docs/extractor_architecture_summary.md
```

## Confirmation that frozen files were untouched

`git diff --stat` against `HEAD` (`7bfcdfd`) is empty for tracked files — the only changes are
the four new, untracked files above. `src/extractors/architecture/base.py`,
`tests/unit/extractors/architecture/test_base.py`, and `tests/integration/test_reference_flow.py`
(frozen as a milestone) are confirmed byte-for-byte unchanged. No `src/parsers/*` file and no
`src/domain/*` file changed. `pyproject.toml` has zero diff — no new dependency was declared in
the manifest (dev/runtime dependencies were installed directly into this sandbox's environment
to run verification, per `pyproject.toml`'s own already-declared `[project.optional-dependencies]
dev` list, plus `mypy`/`ruff` as standalone tooling). No change to any other extractor concern
(`ast`, `imports`, `symbols`), and no dependency-boundary exemption was added for `extractors` or
anywhere else.
