# First Concrete Extractor Summary: `StructuralImportExtractor`

Not a numbered phase. An additive concrete implementation of the already-frozen Phase 6
`ImportExtractor` Port, approved and scoped by the First Extractor — Imports Final Locked
Contract this implements.

## Responsibility

`StructuralImportExtractor` (`src/extractors/imports/structural.py`) turns one file's
already-parsed `ParseResult.imports` into a `tuple[DependencyEdge, ...]` — one edge per import
statement, in the file's own order, duplicates included. It performs no module-path resolution,
no cross-language normalization, no filtering, and no deduplication; assembling many files'
edges into a repository-wide dependency graph remains an explicitly out-of-scope, not-yet-built
`graph` concern.

## Contract

- Zero-argument, stateless: no `__init__` override, exactly like all five concrete `Parser`
  implementations.
- `extract(self, parse_result: ParseResult) -> ImportExtractionResult` — identical signature to
  the abstract method it implements.
- First action: `require_successful_parse(parse_result)`, the already-existing, already-tested
  helper from `base.py`.
- One implementation, five languages: the same instance handles `ParseResult`s from every one of
  `PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, and `CppParser`, since each
  parser already normalizes its own language's import syntax into `ParsedImport` before this
  extractor ever sees it. Verified directly (`test_single_extractor_instance_handles_all_five_
  languages`), not merely assumed from the contract.

## Field mapping

Direct, verbatim copy for every field — no derivation, no computation:

| `DependencyEdge` field | Source |
|---|---|
| `source_path` | `parse_result.relative_path` |
| `target_module` | `parsed_import.module` |
| `imported_names` | `parsed_import.imported_names` |
| `alias` | `parsed_import.alias` |
| `is_internal` | `parsed_import.is_relative` |
| `line_number` | `parsed_import.line_number` |

## Ordering

`edges` preserves `parse_result.imports`' own order exactly — verified with a file whose imports
are in a deliberately non-alphabetical sequence (`zeta`, `alpha`, `middle`), asserting the output
order matches that exact sequence, not a sorted one.

## Duplicate behavior

Preserved, never merged or removed. Two occurrences of the same module (`import os` on two
separate lines) produce two separate edges; `len(edges) == len(parse_result.imports)` always
holds for a successful extraction. The two edges legitimately differ in `line_number`, since each
is a genuinely distinct statement — verified explicitly rather than assumed identical.

## Failure behavior

Exactly one error path: a failed input `ParseResult` causes `require_successful_parse` to raise
`ValidationError` immediately, uncaught, unchanged from its existing behavior. No new exception
type was introduced. `ImportExtractionResult.failed(...)` is never constructed by this
implementation — once given a successful `ParseResult`, the field-by-field mapping above is
total; there is no partial-failure case for this concern to express as data.

## Tests

`tests/unit/extractors/imports/test_base.py` — pre-existing, unchanged, still 12/12 passing.

`tests/unit/extractors/imports/test_structural.py` — 14 new tests: one real-parser case per
language (Python, Rust, Go, TypeScript, C++), one proving a single instance handles all five,
internal vs. external classification (Python relative import, C++ quoted `#include`), empty
imports, duplicate preservation, order preservation, the `ValidationError` failure path, and an
`isinstance` check against the `ImportExtractor` Port itself. Every language case parses a real
source snippet with the real parser — no hand-built `ParsedImport` stands in for parser output.

## Integration test

`tests/integration/test_imports_extraction.py` — new, self-contained (its own local `_config`,
`_clone_repository_func`, `_enumerate_files`, `_parse_files_func`, `_run_git`; does not import
from `tests/integration/test_reference_flow.py`, matching this repository's convention of
self-contained test modules). Creates one real local git repository under `tmp_path` with
`greeter.py` (`import os` — external) and `helpers.py` (`from .greeter import greet` — internal),
runs the Reference Flow's existing three steps plus one new `extract_imports` `MapStep`
(`input_key="parse_results"`, `output_key="import_results"`, `func=StructuralImportExtractor()
.extract`) through `bootstrap(config, extra_steps=[...])`, and asserts the real resulting
`DependencyEdge` data for both files — including the internal file's `target_module=".greeter"`,
`imported_names=("greet",)`, `is_internal=True`. Requires the real `git` executable; skipped, not
failed, when unavailable.

## Verification results

Run against this checkout (`HEAD` = `ccb4d85`, `v0.20.0`, plus the already-frozen Reference Flow
additions), Python 3.12.3:

- `pytest tests/unit/extractors/imports/test_structural.py` — **14 passed**.
- `pytest tests/integration/test_imports_extraction.py` — **1 passed**.
- `pytest` (full suite) — **1332 passed**, 0 failed, the same 2 pre-existing, unrelated
  deprecation warnings as before this work (`starlette`/`httpx`). 1317 (verified baseline before
  this implementation) + 14 + 1 = 1332.
- `mypy --strict src/` — Success: no issues found in **122** source files (121 before this
  implementation, +1 for `structural.py`).
- `ruff check src/ tests/` — exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py`; zero new findings.
- All 125 dependency-boundary tests repo-wide re-run and pass unchanged; no exemption was added
  anywhere.

## Changed files

New files only:

```
src/extractors/imports/structural.py
tests/unit/extractors/imports/test_structural.py
tests/integration/test_imports_extraction.py
docs/extractor_imports_summary.md
```

## Confirmation that frozen files were untouched

`git diff --stat` against `HEAD` (`v0.20.0`) is empty — no tracked file changed. `tests/unit/
extractors/imports/test_base.py` and `tests/integration/test_reference_flow.py` (frozen as a
milestone) are confirmed byte-for-byte unchanged by an explicit `git diff --stat` scoped to each.
`pyproject.toml` has zero diff — no new dependency. No `src/extractors/imports/base.py` change,
no `ParseResult`/`Parser` change, no change to any other extractor concern, and no
dependency-boundary exemption was added for `extractors` or anywhere else.
