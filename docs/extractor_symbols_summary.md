# Third Concrete Extractor Summary: `StructuralSymbolExtractor`

Not a numbered phase. An additive concrete implementation of the already-frozen Phase 6
`SymbolExtractor` Port, approved and scoped by the Symbols Final Locked Contract this implements.

## Responsibility

`StructuralSymbolExtractor` (`src/extractors/symbols/structural.py`) turns one file's
already-parsed `ParseResult` into a `tuple[ExtractedSymbol, ...]` covering the file's classes,
methods, top-level functions, and constants. It performs no scope resolution, no cross-file
analysis, no deduplication, and no naming heuristics; judging reusability or design quality
remains an explicitly out-of-scope concern belonging to `extractors.foundation` and the
not-yet-built `analyzers` phase.

## Contract

- Zero-argument, stateless: no `__init__` override, exactly like `StructuralAstExtractor` and
  `StructuralImportExtractor`.
- `extract(self, parse_result: ParseResult) -> SymbolExtractionResult` — identical signature to
  the abstract method it implements.
- First action: `require_successful_parse(parse_result)`, the already-existing, already-tested
  helper from `base.py`.
- One implementation, five languages: the same instance handles `ParseResult`s from every one of
  `PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, and `CppParser`. Verified directly
  (`test_single_extractor_instance_handles_all_five_languages`), not merely assumed from the
  contract.

## Field mapping

Direct, verbatim copy for every field — no derivation, no computation:

| Source | `kind` | `name` | `line_number` | `qualified_name` |
|---|---|---|---|---|
| `parse_result.classes` | `CLASS` | `cls.name` | `cls.line_number` | `build_qualified_name(relative_path=..., name=cls.name)` |
| each `cls.methods` | `METHOD` | `method.name` | `method.line_number` | `build_qualified_name(relative_path=..., name=method.name, owner=cls.name)` |
| `parse_result.functions` | `FUNCTION` | `function.name` | `function.line_number` | `build_qualified_name(relative_path=..., name=function.name)` |
| `parse_result.symbols` where `kind == SymbolKind.CONSTANT` | `CONSTANT` | `symbol.name` | `symbol.line_number` | `build_qualified_name(relative_path=..., name=symbol.name)` |

`relative_path` on every `ExtractedSymbol` is `parse_result.relative_path`, constant across a
single `extract()` call. `owner` is a parameter of `build_qualified_name`, used only to compute
`qualified_name` for methods — `ExtractedSymbol` itself carries no `owner` field.

`parse_result.modules` is not consumed: `ExtractedSymbolKind` has no `MODULE` member, and this
Port's contract is explicitly scoped to classes, functions (including methods), and constants
only.

## Locked output order

`classes + methods + functions + constants` — all `CLASS` entries first, then all `METHOD`
entries (grouped by owning class, in class-then-method order), then all `FUNCTION` entries, then
all `CONSTANT` entries. Source order is preserved within each of the four groups. Verified
end-to-end with a single file exercising all four kinds at once
(`test_rust_struct_method_function_and_constant_are_extracted`), not just asserted per-kind in
isolation.

This order was not stated explicitly anywhere in the frozen `symbols/base.py` contract prior to
this implementation; it was proposed during contract discovery (grounded in the frozen `go`/
`rust`/`typescript` parsers' own internal symbol-table construction order, which places
`CLASS → METHOD → FUNCTION → ... → CONSTANT`) and explicitly locked by the implementation task
that authorized this file.

## Duplicate behavior

Preserved, never merged or removed, matching the precedent set by `StructuralImportExtractor`.
Two occurrences of the same top-level function name at different lines produce two separate
`ExtractedSymbol` entries (`test_duplicate_top_level_functions_are_preserved`); the same method
name defined on two different classes produces two entries disambiguated by `qualified_name`,
not merged (`test_duplicate_method_names_in_different_classes_produce_different_qualified_
names`).

## Failure behavior

Exactly one error path: a failed input `ParseResult` causes `require_successful_parse` to raise
`ValidationError` immediately, uncaught, unchanged from its existing behavior. No new exception
type was introduced. `SymbolExtractionResult.failed(...)` is never constructed by this
implementation.

## Known parser-level CONSTANT limitations

Two distinct classes of limitation exist in the frozen parser layer, neither corrected here:

1. **Absence.** `PythonParser` and `CppParser` never emit `SymbolKind.CONSTANT` at all, so a
   module-level assignment that reads as a constant to a human (Python's `MAX = 10`, C++'s
   `const int MAX = 10;`) produces no extracted symbol. Explicitly asserted, not silently
   allowed to pass (`test_python_never_extracts_constants_due_to_parser_limitation`,
   `test_cpp_never_extracts_constants_due_to_parser_limitation`).
2. **Over-inclusion.** Despite each parser's own docstring claiming `SymbolKind.CONSTANT` is
   restricted to top-level/module scope, direct execution of the frozen `GoParser`, `RustParser`,
   and `TypeScriptParser` shows this is not actually enforced: a Go `const` declared inside a
   function body, a Rust `const` declared inside an `impl` block, and a TypeScript `const`
   declared inside a function or method body are all emitted identically to a genuine top-level
   constant. `StructuralSymbolExtractor` passes every `SymbolKind.CONSTANT` entry through exactly
   as the parser produced it, with no scope-detection logic — `ParsedSymbol` carries no
   scope/owner information to detect this by, and adding such logic would mean re-deriving
   parser-layer behavior this Port does not own.

Neither limitation is a defect in `StructuralSymbolExtractor`; fixing either would mean changing
a frozen parser, which is out of scope here.

## Tests

`tests/unit/extractors/symbols/test_base.py` — pre-existing, unchanged, still 14/14 passing.

`tests/unit/extractors/symbols/test_structural.py` — 18 new tests: one real-parser case per
language (Python, Rust, Go, TypeScript, C++) — the Rust case exercising all four kinds at once to
prove the locked order end-to-end — one proving a single instance handles all five, the eight
cases required by the implementation task (class+methods+function, constants from a
CONSTANT-emitting parser, VARIABLE never emitted as CONSTANT, empty input, failed input,
duplicate method names across classes, a zero-method class, deterministic repeated extraction),
general duplicate preservation for top-level functions, the two known parser-limitation
assertions above, and an `isinstance` check against the `SymbolExtractor` Port itself. Every
language case parses a real source snippet with the real parser — no hand-built `ParsedClass`/
`ParsedFunction`/`ParsedSymbol` stands in for parser output.

## Integration test

`tests/integration/test_symbols_extraction.py` — new, self-contained (its own local `_config`,
`_clone_repository_func`, `_enumerate_files`, `_parse_files_func`, `_run_git`; does not import
from `tests/integration/test_reference_flow.py`, matching this repository's convention of
self-contained test modules). Creates one real local git repository under `tmp_path` with
`widget.py` (a class with one method) and `helpers.go` (a free function and a top-level
constant), runs the Reference Flow's existing three steps plus one new `extract_symbols`
`MapStep` (`input_key="parse_results"`, `output_key="symbol_results"`, `func=
StructuralSymbolExtractor().extract`) through `bootstrap(config, extra_steps=[...])`, and asserts
the real resulting `ExtractedSymbol` data for both files, including the locked ordering.
Requires the real `git` executable; skipped, not failed, when unavailable.

## Verification results

Run against this checkout (`HEAD` = `db8b2ab`), Python 3.12.3 (this sandbox has no Python 3.13
interpreter available; the project's `pyproject.toml` pins `requires-python = ">=3.13"` and
`mypy`'s `python_version = "3.13"` target was honored as configured — only the interpreter used
to *run* the tests differs from the pinned version; no language feature used here is
version-sensitive between 3.12 and 3.13):

- `pytest tests/unit/extractors/symbols/test_structural.py` — **18 passed**.
- `pytest tests/integration/test_symbols_extraction.py` — **1 passed**.
- `pytest` (full suite) — **1362 passed**, 0 failed, the same 2 pre-existing, unrelated
  deprecation warnings as before this work (`starlette`/`httpx`). 1343 (verified baseline before
  this implementation) + 18 + 1 = 1362.
- `mypy --strict src/` — Success: no issues found in **124** source files (123 before this
  implementation, +1 for `structural.py`).
- `ruff check src/ tests/` — exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py`; zero new findings.
- `tests/unit/repository/test_git.py::test_default_branch_matches_the_origin` — passed in this
  environment (this is the test flagged as a known, environment-dependent pre-existing failure
  elsewhere; it did not fail here, and was not modified).

## Changed files

New files only:

```
src/extractors/symbols/structural.py
tests/unit/extractors/symbols/test_structural.py
tests/integration/test_symbols_extraction.py
docs/extractor_symbols_summary.md
```

## Confirmation that frozen files were untouched

`git diff --stat` against `HEAD` (`db8b2ab`) is empty — no tracked file changed. `src/extractors/
symbols/base.py`, `tests/unit/extractors/symbols/test_base.py`, and `tests/integration/
test_reference_flow.py` (frozen as a milestone) are confirmed byte-for-byte unchanged by explicit
`git diff --stat` scoped to each. `pyproject.toml` has zero diff — no new dependency was declared
in the manifest (dev/runtime dependencies were installed directly into this sandbox's environment
to run verification, per `pyproject.toml`'s own already-declared `[project.optional-dependencies]
dev` list). No `src/extractors/symbols/base.py` change, no `ParseResult`/`Parser` change, no
change to any other extractor concern (`ast`, `imports`), and no dependency-boundary exemption
was added for `extractors` or anywhere else.
