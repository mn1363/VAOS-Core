# Second Concrete Extractor Summary: `StructuralAstExtractor`

Not a numbered phase. An additive concrete implementation of the already-frozen Phase 6
`AstExtractor` Port, approved and scoped by the AST Extractor — Final Locked Contract this
implements, itself derived from the Next Concrete Extractor Discovery that selected `ast` as the
extractor to build after `extractors.imports`.

## Purpose

`StructuralAstExtractor` (`src/extractors/ast/structural.py`) turns one file's already-parsed
`ParseResult` into a single `AstMetadata` record — eleven non-negative structural counts
(classes, free functions, methods, imports, exports, symbols, nested modules, async functions,
documented classes, documented functions, lines). It is a counting-only extractor: it answers
*how much* structure a file has, never whether that structure is good, complex, or reusable.
Complexity/quality scoring belongs to the future `analyzers` phase; foundation-worthiness
belongs to `extractors.foundation`. Neither is performed here.

## Contract

- Zero-argument, stateless: no `__init__` override, exactly like `StructuralImportExtractor` and
  all five concrete `Parser` implementations.
- `extract(self, parse_result: ParseResult) -> AstExtractionResult` — identical signature to the
  abstract method it implements.
- First action: `require_successful_parse(parse_result)`, the already-existing, already-tested
  helper from `base.py`.
- One implementation, five languages: the same instance handles `ParseResult`s from every one of
  `PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, and `CppParser`, since every count
  is derived purely from fields each parser already normalizes into the same `ParseResult` shape.
  Verified directly (`test_single_extractor_instance_handles_all_five_languages`), not merely
  assumed from the contract.

## Field-by-field derivation

Pure counting — no derivation requires anything beyond `len()`, `sum()`, or a boolean predicate
over fields `ParseResult` already carries:

| `AstMetadata` field | Derivation |
|---|---|
| `class_count` | `len(parse_result.classes)` |
| `function_count` | `len(parse_result.functions)` |
| `method_count` | `sum(len(cls.methods) for cls in parse_result.classes)` |
| `import_count` | `len(parse_result.imports)` |
| `export_count` | `len(parse_result.exports)` |
| `symbol_count` | `len(parse_result.symbols)` |
| `module_count` | `len(parse_result.modules)` |
| `async_function_count` | `is_async=True` count across `functions` + every class's `methods` |
| `documented_class_count` | `docstring is not None` count across `classes` |
| `documented_function_count` | `docstring is not None` count across `functions` + every class's `methods` |
| `line_count` | `parse_result.metadata.line_count` |

Documentation counting uses `docstring is not None`, never a truthiness check — a docstring
literal that is empty once stripped (`""" """` → `""`) is still present, and must still count as
documented. Verified explicitly (`test_empty_docstring_still_counts_as_documented`).

## Counting-only responsibility; no inference, resolution, or normalization

No sorting, filtering, deduplication, or normalization is applied beyond the exact predicates
above. Duplicates in the input are naturally reflected, never collapsed — two identical imports
still contribute `2` to `import_count`. There is no cross-file aggregation and no module
resolution; each call is scoped to exactly the one `ParseResult` it is given.

## Known parser-layer limitations (disclosed, not worked around)

None of these is a defect in `StructuralAstExtractor` — each is a property of what the
already-frozen parser layer does or does not carry into `ParseResult`, and none is fixed here.

- **Go never carries any docstring at all.** `GoParser` never sets `docstring` on any
  `ParsedFunction` or `ParsedClass` it produces — `documented_class_count` and
  `documented_function_count` are `0` for every Go file, regardless of how well the source is
  actually documented with `//` comments. Verified with genuinely documented Go source
  (`test_go_documented_source_still_produces_zero_documented_counts`, and end to end in the
  integration test).
- **TypeScript and C++ never carry a docstring for in-class methods**, only for classes and free
  functions. Both parsers' `_build_method` (the function that turns a class member into a
  `ParsedFunction`) never sets `docstring`, even when a real JSDoc block (TypeScript) or `///`
  comment (C++) immediately precedes the method in the source — only their respective
  free-function-building code paths call the doc-comment-detection helper. This is a real
  parser-layer limitation discovered during this implementation's own verification against real
  source (it was not surfaced by the earlier discovery/contract passes) and is asserted
  explicitly in both language's tests (`test_typescript_class_and_free_function_docstrings_are_
  counted`, `test_cpp_class_and_free_function_docstrings_are_counted`), each documenting a class
  and a free function correctly while a documented method's docstring is confirmed absent.
- **Nested classes are invisible to `ParseResult` for every language.** A class declared inside
  another class or inside a function is not collected as its own entry (`PythonParser`'s own
  docstring states this explicitly; the other four parsers' shared depth-0-member-scanning
  primitives imply the same for their languages). `class_count`/`method_count` will never reflect
  such a class, for any of the five languages, because no parser surfaces one.
- **Python has no nested-module construct**, so `module_count` is always `0` for Python files —
  `ParsedModule` exists for Rust's `mod`, Go's `package`, TypeScript's `namespace`/`module`, and
  C++'s `namespace`, none of which Python has an equivalent of.

## Relationship to `ParseResult`; no parser-layer change

Every field is read directly from `ParseResult`'s own already-defined attributes
(`classes`, `functions`, `imports`, `exports`, `symbols`, `modules`, `metadata.line_count`); none
is added, renamed, or reinterpreted. `parse_result.metadata` is accessed only after
`require_successful_parse` has confirmed `succeeded=True`, which is what guarantees it is not
`None` (per `ParseResult`'s own documented invariant) — narrowed with an explicit `assert`, not a
silent cast. No `Parser` implementation, `ParseResult`, `AstExtractor`, `AstMetadata`,
`AstExtractionResult`, or `require_successful_parse` was modified.

## Failure behavior

Exactly one error path: a failed input `ParseResult` causes `require_successful_parse` to raise
`ValidationError` immediately, uncaught, unchanged from its existing behavior. No new exception
type was introduced. `AstExtractionResult.failed(...)` is never constructed by this
implementation — once given a successful `ParseResult`, the field-by-field mapping above is
total; there is no partial-failure case for this concern to express as data.

## Tests

`tests/unit/extractors/ast/test_base.py` — pre-existing, unchanged, still 13/13 passing.

`tests/unit/extractors/ast/test_structural.py` — 10 new tests: one real-parser case per language
(Python, Rust, Go, TypeScript, C++), one proving a single instance handles all five, an all-zero
empty-file case, the empty-docstring-still-counts case, the `ValidationError` failure path, and
an `isinstance` check against the `AstExtractor` Port itself. The Python case is a single mixed
file deliberately exercising every one of the eleven fields at once (two classes, three methods,
two free functions, two imports, a two-name `__all__` export list, one async method, one async
free function, one documented class, one documented free function). Every expected count in this
file was obtained by running the real parser and the real extractor together first and reading
off the result, not hand-derived from the snippet alone — this is how the TypeScript/C++
method-docstring gap above was actually found.

## Integration test

`tests/integration/test_ast_extraction.py` — new, self-contained (its own local `_config`,
`_all_parsers`, `_clone_repository_func`, `_enumerate_files`, `_parse_files_func`, `_run_git`;
does not import from `tests/integration/test_reference_flow.py`, matching this repository's
convention of self-contained test modules). Creates one real local git repository under
`tmp_path` with `greeter.py` (a documented sync function plus an undocumented async function)
and `widget.go` (a genuinely `//`-documented struct and constructor function), runs the
Reference Flow's existing three steps plus one new `extract_ast` `MapStep`
(`input_key="parse_results"`, `output_key="ast_results"`, `func=StructuralAstExtractor().
extract`) through `bootstrap(config, extra_steps=[...])`, and asserts the real resulting
`AstMetadata` for both files — including the Go file's documented-count-is-zero behavior,
verified end to end through the real flow, not just in isolation. Requires the real `git`
executable; skipped, not failed, when unavailable.

## Verification results

Run against this checkout (`HEAD` = `8396e62`, one commit past `v0.20.0`, plus the already-frozen
`extractors.imports` and Reference Flow), Python 3.12.3:

- `pytest tests/unit/extractors/ast/test_structural.py` — **10 passed**.
- `pytest tests/integration/test_ast_extraction.py` — **1 passed**.
- `pytest` (full suite) — **1343 passed**, 0 failed, the same 2 pre-existing, unrelated
  deprecation warnings as before this work (`starlette`/`httpx`). 1332 (verified baseline before
  this implementation) + 10 + 1 = 1343.
- `mypy --strict src/` — Success: no issues found in **123** source files (122 before this
  implementation, +1 for `structural.py`).
- `ruff check src/ tests/` — exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py`; zero new findings.

## Changed files

New files only:

```
src/extractors/ast/structural.py
tests/unit/extractors/ast/test_structural.py
tests/integration/test_ast_extraction.py
docs/extractor_ast_summary.md
```

## Confirmation that frozen files were untouched

`git diff --stat` against `HEAD` (`8396e62`) is empty — no tracked file changed. `git status`
lists exactly three untracked source/test files before this document was written (the fourth).
`tests/unit/extractors/ast/test_base.py` and `tests/integration/test_reference_flow.py` (frozen
as a milestone) are confirmed byte-for-byte unchanged. `pyproject.toml` has zero diff — no new
dependency. No `src/extractors/ast/base.py` change, no `ParseResult`/`Parser` change,
no `src/extractors/imports/structural.py` change, no change to any other extractor concern, and
no dependency-boundary exemption was added for `extractors` or anywhere else.
