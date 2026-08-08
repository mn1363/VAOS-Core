# VAOS Phase 5 — Parsers Layer Summary

**Scope:** `src/parsers/__init__.py`, `base.py`, and one `parser.py` per
language subpackage — `python/`, `rust/`, `go/`, `typescript/`, `cpp/` —
exactly the five-language, one-file-per-language structure specified for
this phase.
**`src/core`, `src/domain`, `src/repository`, and `src/collectors` were not
modified.** `pyproject.toml` was not modified — no new dependency was
needed this phase.
**Generated:** 2026-08-08

## What this layer does

`parsers` answers one question: *what is structurally present in a single
already-read source file?* Given a `relative_path` and the file's `content`
as an already-decoded string, a `Parser` extracts modules, classes,
functions, imports, exports, symbols, and file metadata — and nothing
else. It performs no business logic, no architecture analysis, no scoring,
and no graph generation. It also does not read files itself (that's
`collectors`/`repository`, already built) and does not persist results
(that's `storage`, a later phase) — both deliberately out of scope here,
matching the frozen separation between these packages.

- **`base.py`** — the `Parser` Port (`language` property, `supports
  (relative_path)`, and synchronous `parse(*, relative_path, content) ->
  ParseResult`) and every parsed-construct DTO: `ParseResult`,
  `FileMetadata`, `ParsedModule`, `ParsedClass`, `ParsedFunction`,
  `ParsedImport`, `ParsedExport`, `ParsedSymbol`, `SymbolKind`. `parse` is
  synchronous, not `async` like `collectors.base.Collector.collect` — it
  performs no I/O of its own, so parsing is pure, in-memory, CPU-bound
  work, and every `Parser` is trivially constructible with zero arguments.
  Like `CollectionResult`, `ParseResult` reports failure (e.g. a syntax
  error) through the returned result rather than raising, with its own
  `__post_init__` invariant checks reusing `core.exceptions.ValidationError`
  rather than introducing a new package-specific exception — the same
  reuse-over-invention principle `collectors` and `domain` both follow.
  `base.py` also holds the shared low-level scanning primitives the four
  regex-based parsers below all build on: `strip_c_style_comments`,
  `find_matching_brace`/`find_matching_paren`, `split_top_level`,
  `line_number_at`, `is_top_level_of_span`, and `leading_comment_lines` —
  each generic to any `//`/`/* */`-commented, brace-delimited language, so
  each lives here once rather than being duplicated four times.
- **`python/parser.py`** — `PythonParser`, which delegates entirely to the
  standard library `ast` module rather than a hand-written grammar. Python
  ships its own exact, always-in-sync parser as part of the interpreter
  running this code, so this is the one language in this phase with
  perfect-fidelity parsing rather than a heuristic scan. `modules` is
  always empty for Python — it has no construct for declaring a nested
  module boundary within a single file. `__all__`, when present, becomes
  the file's `exports`.
- **`rust/parser.py`**, **`go/parser.py`**, **`typescript/parser.py`**,
  **`cpp/parser.py`** — one `Parser` per language, all four built the same
  way: a lightweight, regular-expression-based structural scan over the
  file's comment-blanked text, reading real source text (never comments)
  back out of the *original* content using the same offsets, since
  `strip_c_style_comments` preserves exact length and line layout. No
  external parser or grammar dependency was added; `pyproject.toml` is
  unchanged. Each maps its language's closest OOP-like construct onto
  `ParsedClass` — Rust `struct` (with `impl`/`impl Trait for` blocks
  supplying methods and base traits), Go `struct` (with receiver-method
  matching), C++ `class`/`struct` — while a language's *interface-shaped*
  construct (Rust `trait`, TypeScript `interface`) is reported as a
  `SymbolKind` symbol instead, since it has no method bodies of its own to
  collect. "Exported" reuses each language's own visibility mechanism
  rather than one invented convention: Rust/Rust-adjacent `pub`, Go's
  capitalized-identifier convention, TypeScript's `export` keyword and
  `export {}`/`export *` forms, and C++20's `export` keyword (ordinary,
  pre-modules C++ has no such concept, so `exports` is typically empty
  there — matching this package's general "where applicable" framing).

## Two real bugs found and fixed during this phase's own verification

Both were caught by writing (and reading the actual output of) functional
tests against realistic samples, not assumed correct from the regex
pattern alone — the same discipline applied throughout this phase.

1. **Go: `const`/`var` misclassification.** An early version classified a
   top-level `const`/`var` name as `SymbolKind.CONSTANT` vs `VARIABLE`
   using `name.isupper()` (an unreliable naming-convention guess) instead
   of the actual declaring keyword, so `const MaxRetries = 3` was
   misclassified as a variable. Fixed by threading the real `const`/`var`
   keyword through extraction instead of guessing from casing.
2. **TypeScript and C++: a call statement mistaken for a sibling method.**
   The first version of both class-method scans matched any
   `identifier(` at the start of a line inside a class body — which also
   matches a plain call statement like `doSomething(a, b);` sitting inside
   some *other* method's body. Fixed by adding `is_top_level_of_span`
   (checking that the match sits at brace depth 0 relative to the class
   body, not nested inside a sibling method's own `{ }`) to `base.py`, and
   using it in both parsers. C++'s free-function scan had the same defect
   one level up (a `return computeTotal(a, b);` inside `main()` looked
   like a new top-level function) — fixed with a whole-file opaque-depth
   computation (`_compute_opaque_depths`) that treats `namespace` blocks as
   transparent but every other block (function bodies, `if`/`for`/`while`/
   `switch`/`catch`, class bodies) as depth-increasing.

## Documented, deliberate scope limitations

Each is a bounded trade-off of a lightweight structural scan over a real
parser front end, not an oversight — noted in-line in the relevant
docstring, and repeated here for visibility:

- The four regex-based parsers recognize common, conventionally-formatted
  declarations; they do not compute full nesting depth for arbitrary block
  nesting. A named `function` declared *inside another function's* body in
  TypeScript (legal, if unusual) is still reported as a free function.
- Comment/string-literal interaction: `strip_c_style_comments` does not
  recognize string or character literals, so a literal containing `//` or
  `/*` (a Rust raw string, a TypeScript template literal) can in rare
  cases be mistaken for a comment's start.
- C++ only matches *in-class-body* member declarations as methods; an
  out-of-class definition (`ReturnType ClassName::method(...) { ... }`) is
  not matched back to its class.
- Go struct field embedding (Go's composition-based analogue to
  inheritance) is not resolved into `base_classes` — Go has no explicit
  `extends`/`implements` declaration the way the other languages do.
- Rust/TypeScript/C++/Go `use`/`import`/`#include` grouping is supported
  one level deep; a doubly-nested Rust `use` group
  (`use std::{fmt::{self, Display}, ...}`) is not fully expanded.

## Counts

| Metric | Count |
|---|---|
| Parsers source files (`src/parsers/**/*.py`) | 12 |
| Parsers test files (`test_*.py`) | 6 |
| Parsers test functions (test cases after parametrization) | 137 (164) |
| **Total project test count (Core + Domain + Repository + Collectors + Parsers)** | **339** |
| Total source files (`src/**/*.py`) | 34 |
| Total test files (`tests/**/*.py`) | 36 |
| Parsed-construct DTOs + Port in `parsers.base` | 10 (`Parser`, `ParseResult`, `FileMetadata`, `ParsedModule`, `ParsedClass`, `ParsedFunction`, `ParsedImport`, `ParsedExport`, `ParsedSymbol`, `SymbolKind`) |
| Concrete `Parser` implementations | 5 (`PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, `CppParser`) |

## Verification (all steps)

1. **Import validation** — every file in `src/parsers/` and its 5 language
   subpackages import successfully under the project's `src.`-prefixed
   convention, individually verified via `importlib.import_module`, plus a
   combined run instantiating all five concrete parsers and asserting each
   `isinstance(parser, Parser)`.
2. **AST/grep-level dependency validation** — every `import`/`from`
   statement in `src/parsers/**/*.py` was enumerated: every file imports
   only stdlib, `src.core.exceptions`, `src.domain.entities`, and the
   intra-package `..base` — nothing else. No file imports any of the
   explicitly forbidden packages (`collectors`, `repository`, `extractors`,
   `analyzers`, `graph`, `foundation`, `storage`, `memory`, `pipeline`,
   `plugins`, `api`, `cli`), confirmed by an explicit negative grep that
   found zero matches.
3. **Architecture boundary validation** — confirmed no language
   subpackage imports a sibling language subpackage
   (`src.parsers.rust` never imports from `src.parsers.go`, etc.) — each
   is independently self-contained aside from the shared `base.py`.
4. **Circular dependency check** — package-level graph extends to
   `parsers → {core, domain}`. No cycles. Reverse-direction check
   confirmed neither `core` nor `domain` reference `parsers` (the one
   textual hit is a docstring comment in `domain/entities.py` describing
   the frozen phase-by-phase layout, not an import).
5. **Unit tests** — 164/164 pass for this layer (339/339 for the whole
   project). Every parser is exercised against realistic, multi-construct
   source samples (not single-line toys) covering imports (plain, named,
   grouped, aliased, relative, wildcard), classes with base lists and
   docstrings, methods vs. free functions, async, exports, and the two
   bug-fix regressions above (a call statement inside a method/function
   body must never be reported as a sibling declaration). `test_base.py`
   covers every shared DTO invariant and every low-level scanning helper
   directly, parametrized over blank-path and malformed-input cases.
6. **mypy --strict** — clean on `src/core` + `src/domain` +
   `src/repository` + `src/collectors` + `src/parsers` (33 files) and on
   the full `tests` tree (36 files, informational), targeting
   `--python-version 3.13` per `pyproject.toml`.
7. **Ruff** — **fully clean within this phase's scope** (`src/parsers/` +
   `tests/unit/parsers/`). One finding remains project-wide (`UP046` on
   `Repository`'s `Generic[EntityT]` base in `src/domain/interfaces.py`) —
   pre-existing from Phase 2, already reviewed and accepted there, noted
   again untouched in the Phase 4 audit, and left untouched here per this
   phase's explicit instruction not to modify `src/domain/`. See
   `ruff_report.txt` for both the full and scoped runs.

## A note on the Python version used to run verification

This sandboxed environment has Python 3.12.3 available (no 3.13
interpreter or package is installable here — checked directly via `apt`
against this Ubuntu 24.04 image's package sources). `pytest_report.txt`
and the interpreter-dependent parts of `mypy_report.txt` reflect that.
`mypy --strict` was still run with `--python-version 3.13` (mypy's target
semantics are governed by this flag, largely independent of the
interpreter running mypy itself), matching `pyproject.toml`'s
`[tool.mypy] python_version = "3.13"`. No 3.13-exclusive syntax was used
anywhere in this phase's code. This same substitution was already present,
unremarked, in Phase 4's own `pytest_report.txt` (`platform linux --
Python 3.12.3`), so it is not a new deviation introduced here.

## Package contents added this phase

```
src/parsers/
├── __init__.py
├── base.py                (Parser Port, ParseResult + 7 other DTOs, shared scanning helpers)
├── python/
│   ├── __init__.py
│   └── parser.py            (PythonParser — stdlib ast-backed)
├── rust/
│   ├── __init__.py
│   └── parser.py              (RustParser — struct/impl/trait/use scan)
├── go/
│   ├── __init__.py
│   └── parser.py                (GoParser — struct/receiver-method/package scan)
├── typescript/
│   ├── __init__.py
│   └── parser.py                  (TypeScriptParser — class/interface/import/export scan)
└── cpp/
    ├── __init__.py
    └── parser.py                    (CppParser — class/struct/namespace/include scan)

tests/unit/parsers/
├── __init__.py
├── test_base.py            (36 test functions, 43 cases)
├── python/test_parser.py     (20 tests)
├── rust/test_parser.py         (20 tests)
├── go/test_parser.py             (17 tests)
├── typescript/test_parser.py       (23 tests)
└── cpp/test_parser.py                (21 tests)

docs/
├── phase5_summary.md   (this file)
├── pytest_report.txt   (updated: now covers the full 339-test suite)
├── mypy_report.txt     (updated: now covers src/parsers + tests/unit/parsers)
└── ruff_report.txt     (updated: now covers src/parsers + tests/unit/parsers)
```

## Not implemented this phase

Every other package (`extractors`, `analyzers`, `graph`, `foundation`,
`storage`, `memory`, `pipeline`, `api`, `cli`, `plugins`) — none were
touched. No file-reading, persistence, architecture analysis, scoring, or
graph generation happens anywhere in this layer, by design (see "What this
layer does," above) — a `Parser` only ever transforms an in-memory
`content: str` it was handed into a `ParseResult`.

---

**Phase 5 complete. `src/core`, `src/domain`, `src/repository`, and
`src/collectors` unmodified. Next phase not started — awaiting your
instruction.**
