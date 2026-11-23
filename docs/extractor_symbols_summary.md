# Third Concrete Extractor Summary: `StructuralSymbolExtractor`

Not a numbered phase. An additive concrete implementation of the already-frozen Phase 6
`SymbolExtractor` Port, approved and scoped by the Symbols Final Locked Contract this implements.

This document describes the extractor's **current** behavior. Statements that record the state of
the original milestone (verification results, changed files, the frozen-file confirmation) are
labeled as such and kept as history; what changed afterwards is listed under
[Amendments since the original milestone](#amendments-since-the-original-milestone).

## Responsibility

`StructuralSymbolExtractor` (`src/extractors/symbols/structural.py`) turns one file's
already-parsed `ParseResult` into a `tuple[ExtractedSymbol, ...]` covering the file's classes,
class methods, TypeScript interface methods and interface properties, top-level functions, and
constants. It performs no scope resolution, no cross-file analysis, no deduplication, and no
naming heuristics; judging reusability or design quality remains an explicitly out-of-scope
concern belonging to `extractors.foundation` and the not-yet-built `analyzers` phase.

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
  contract. Only `TypeScriptParser` populates `ParseResult.interfaces`, so interface methods and
  interface properties come from TypeScript files only; see
  [Interface members](#interface-members-typescript).

## Symbol kinds

`ExtractedSymbolKind` has five members, a deliberately narrow subset of `parsers.base.SymbolKind`:

| Kind | Value | Produced for |
|---|---|---|
| `CLASS` | `class` | Each parsed class |
| `FUNCTION` | `function` | Each parsed top-level function |
| `METHOD` | `method` | Each class method, and each TypeScript interface method signature |
| `CONSTANT` | `constant` | Each `SymbolKind.CONSTANT` parser symbol |
| `PROPERTY` | `property` | Each TypeScript interface property |

There is no `MODULE` kind: `parse_result.modules` is not consumed.

## Field mapping

Direct, verbatim copy for every field — no derivation, no computation:

| Source | `kind` | `name` | `line_number` | `qualified_name` |
|---|---|---|---|---|
| `parse_result.classes` | `CLASS` | `cls.name` | `cls.line_number` | `build_qualified_name(relative_path=..., name=cls.name)` |
| each `cls.methods` | `METHOD` | `method.name` | `method.line_number` | `build_qualified_name(relative_path=..., name=method.name, owner=cls.name)` |
| each `interface.methods` of `parse_result.interfaces` | `METHOD` | `method.name` | `method.line_number` | `build_qualified_name(relative_path=..., name=method.name, owner=interface.name)` |
| each `interface.properties` of `parse_result.interfaces` | `PROPERTY` | `prop.name` | `prop.line_number` | `build_qualified_name(relative_path=..., name=prop.name, owner=interface.name)` |
| `parse_result.functions` | `FUNCTION` | `function.name` | `function.line_number` | `build_qualified_name(relative_path=..., name=function.name)` |
| `parse_result.symbols` where `kind == SymbolKind.CONSTANT` | `CONSTANT` | `symbol.name` | `symbol.line_number` | `build_qualified_name(relative_path=..., name=symbol.name)` |

`relative_path` on every `ExtractedSymbol` is `parse_result.relative_path`, constant across a
single `extract()` call. `owner` is a parameter of `build_qualified_name`, used only to compute
`qualified_name` for class methods, interface methods, and interface properties —
`ExtractedSymbol` itself carries no `owner` field.

`parse_result.modules` is not consumed: `ExtractedSymbolKind` has no `MODULE` member, and this
Port's contract is scoped to classes, functions, methods, constants, and interface properties.

## Interface members (TypeScript)

`TypeScriptParser` reports each file-scope `interface` declaration as a `ParsedInterface` carrying
its `methods` and its `properties`. The extractor copies both onto `ExtractedSymbol`s, qualified
by the interface's own name. The other four parsers produce no `ParsedInterface` entries, so their
extraction is unchanged and never yields a `PROPERTY` symbol
(`test_other_language_parsers_never_produce_property_symbols`). Python's ABC/Protocol classes
are ordinary parsed classes to this extractor. Rust traits and Go interfaces are not mapped to
symbols by it: it never reads `INTERFACE`- or `TRAIT`-kind entries of `parse_result.symbols`, which
belong to the separate `extractors.interfaces` extractor.

**Interface methods** are the method, optional method, generic method, getter, and setter
signatures the parser finds directly in an interface body. Each becomes a `METHOD` symbol, e.g.
`ports.ts::Repository.findById`. The interface's type parameters are not part of the owner name.
A getter and a setter of the same name produce two entries with the same qualified name, because
duplicates are preserved.

**Interface properties** are the named data members of an interface body — `id: string`,
`age?: number`, `readonly createdAt: Date`, `readonly tags?: string[]`, quoted names such as
`"content-type": string`, numeric names such as `0: boolean`, several members on one line, and
members separated by `;`, `,` or a line break. Each becomes a `PROPERTY` symbol:

- **Kind:** `ExtractedSymbolKind.PROPERTY` (value `property`).
- **Name and owner:** `name` is the property's own name (a quoted name without its quotes), and the
  owner is the interface, so `interface User { id: string }` in `ports.ts` yields
  `qualified_name == "ports.ts::User.id"`. The qualified name is built only from the file path,
  the interface name, and the property name.
- **Distinct across interfaces:** `Reader.id` and `Writer.id` in the same file are different
  symbols with different qualified names
  (`test_typescript_same_property_name_in_two_interfaces_stays_distinct`).
- **Line number:** the 1-indexed line the property is declared on, as the parser reported it
  (`test_typescript_interface_properties_are_extracted_as_property_symbols`).
- **What is not carried over:** the property's type, optionality, and `readonly` status exist on
  the parser's `ParsedProperty`; `ExtractedSymbol` has no field for them, so they do not reach the
  symbol or the knowledge graph.
- **Duplicates:** two declarations of the same property name in one interface (for example through
  repeated declarations) are both kept and share one qualified name.

Not properties, and therefore never `PROPERTY` symbols: method signatures (reported as `METHOD`),
getters and setters (also `METHOD`), call signatures, construct signatures, index signatures, and
computed names such as `[Symbol.iterator]`. Class fields are not interface properties either, and
the TypeScript parser does not report them. An interface declared inside a function body or other
non-file-scope block is not reported by the parser and so yields no symbols; an interface inside a
`namespace` is reported like any other.

## Locked output order

`classes + methods + interface_methods + interface_properties + functions + constants` — all
`CLASS` entries first, then all class `METHOD` entries (grouped by owning class, in
class-then-method order), then all interface `METHOD` entries (grouped by owning interface), then
all interface `PROPERTY` entries (grouped by owning interface), then all `FUNCTION` entries, then
all `CONSTANT` entries. Source order is preserved within each of the six groups. Verified
end-to-end with a single file exercising all four original kinds at once
(`test_rust_struct_method_function_and_constant_are_extracted`), and with a TypeScript file
mixing classes, interface methods, interface properties, a function, and a constant
(`test_typescript_interface_property_and_method_symbols_are_not_confused`), not just asserted
per-kind in isolation.

The original four-group order (`classes + methods + functions + constants`) was not stated
explicitly anywhere in the frozen `symbols/base.py` contract prior to this implementation; it was
proposed during contract discovery (grounded in the frozen `go`/`rust`/`typescript` parsers'
own internal symbol-table construction order, which places `CLASS → METHOD → FUNCTION → ... →
CONSTANT`) and explicitly locked by the implementation task that authorized this file. The two
interface groups were later inserted between class methods and functions, so that the declaration
members of a type stay together and ahead of free functions.

## Duplicate behavior

Preserved, never merged or removed, matching the precedent set by `StructuralImportExtractor`.
Two occurrences of the same top-level function name at different lines produce two separate
`ExtractedSymbol` entries (`test_duplicate_top_level_functions_are_preserved`); the same method
name defined on two different classes produces two entries disambiguated by `qualified_name`,
not merged (`test_duplicate_method_names_in_different_classes_produce_different_qualified_
names`). The same applies to interface members: an interface method or property with the same
name in two different interfaces is two entries with different qualified names.

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

`tests/unit/extractors/symbols/test_base.py` — pre-existing and not modified by this extractor
work.

`tests/unit/extractors/symbols/test_structural.py` — 26 tests:

- The 18 original tests: one real-parser case per language (Python, Rust, Go, TypeScript, C++) —
  the Rust case exercising all four original kinds at once to prove the locked order end-to-end —
  one proving a single instance handles all five, the eight cases required by the implementation
  task (class+methods+function, constants from a CONSTANT-emitting parser, VARIABLE never emitted
  as CONSTANT, empty input, failed input, duplicate method names across classes, a zero-method
  class, deterministic repeated extraction), general duplicate preservation for top-level
  functions, the two known parser-limitation assertions above, and an `isinstance` check against
  the `SymbolExtractor` Port itself.
- One test for interface methods keeping distinct owners
  (`test_typescript_interface_methods_keep_distinct_owners`).
- Seven tests for interface properties: the `property` kind value, extraction of required,
  optional, readonly and optional-readonly properties with qualified names and line numbers, a
  generic interface keeping its bare-name owner, same-named properties of different interfaces
  staying distinct, properties and methods keeping their own kinds within the locked order,
  unique qualified names for differently named properties, and the other four parsers producing no
  `PROPERTY` symbols.

Every language case parses a real source snippet with the real parser — no hand-built
`ParsedClass`/`ParsedFunction`/`ParsedSymbol`/`ParsedInterface` stands in for parser output.

## Integration tests

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

Interface property symbols are additionally exercised end-to-end, through real parsers and the
real extractor into the knowledge graph, by `tests/integration/test_knowledge_graph.py`; see
`docs/knowledge_graph_builder_summary.md`.

## Amendments since the original milestone

The extractor was extended without changing its Port, its identity policy
(`build_qualified_name`), or its failure behavior:

- **Interface methods.** `parse_result.interfaces[*].methods` now produce `METHOD` symbols
  qualified by the interface name.
- **Interface properties.** `parse_result.interfaces[*].properties` produce `PROPERTY` symbols
  qualified by the interface name. `ExtractedSymbolKind` gained the `PROPERTY` member; the four
  existing members and their values are unchanged.
- **Output order.** The interface-method and interface-property groups were inserted between the
  class-method and function groups.
- **Parser layer.** `ParsedProperty` was added to `parsers.base` and `ParsedInterface` gained a
  trailing `properties` field defaulting to `()`; `TypeScriptParser` populates them. Other
  parsers are unchanged.

Files changed by these amendments: `src/extractors/symbols/base.py`,
`src/extractors/symbols/structural.py`, `src/parsers/base.py`, `src/parsers/typescript/parser.py`,
and the corresponding unit and integration tests.

## Verification results (original milestone)

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

These figures describe that milestone only; they are not the current suite.

## Changed files (original milestone)

New files only:

```
src/extractors/symbols/structural.py
tests/unit/extractors/symbols/test_structural.py
tests/integration/test_symbols_extraction.py
docs/extractor_symbols_summary.md
```

## Frozen-file confirmation (original milestone)

At that milestone, `git diff --stat` against `HEAD` (`db8b2ab`) was empty — no tracked file
changed. `src/extractors/symbols/base.py`, `tests/unit/extractors/symbols/test_base.py`, and
`tests/integration/test_reference_flow.py` (frozen as a milestone) were confirmed byte-for-byte
unchanged by explicit `git diff --stat` scoped to each. `pyproject.toml` had zero diff — no new
dependency was declared in the manifest (dev/runtime dependencies were installed directly into
that sandbox's environment to run verification, per `pyproject.toml`'s own already-declared
`[project.optional-dependencies] dev` list). No `ParseResult`/`Parser` change, no change to any
other extractor concern (`ast`, `imports`), and no dependency-boundary exemption was added for
`extractors` or anywhere else.

That confirmation no longer holds for `src/extractors/symbols/base.py`, which the amendments above
changed additively (the `PROPERTY` kind and docstring updates), nor for `ParseResult`-related
parser DTOs, which gained `ParsedProperty`. `pyproject.toml` is still unchanged.
