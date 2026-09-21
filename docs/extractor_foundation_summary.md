# Concrete Extractor Summary: `StructuralFoundationExtractor`

Not a numbered phase. An additive concrete implementation of the already-frozen Phase 6
`FoundationExtractor` Port, approved and scoped by the Foundation Extractor Contract Discovery
and Final Contract Lock passes this implements (sixth concrete extractor, after `imports`,
`ast`, `symbols`, `architecture`, and `interfaces`).

## Responsibility

`StructuralFoundationExtractor` (`src/extractors/foundation/structural.py`) turns one file's
already-parsed `ParseResult` into its `FoundationCandidate` entries — one per parsed class and
one per parsed top-level function. It is per-file and purely mechanical: it copies names, paths,
and lines, and applies exactly two boolean predicates over data the frozen parser layer already
carries. It performs no quality analysis, no ranking, no selection, no merging, no cross-file
aggregation, and no judgment about whether a candidate is worth reusing; see
`FoundationExtractor`'s own `base.py` docstring for what is deliberately out of scope. Combining
candidates' fields into a score, and choosing which become a foundation, belongs to the later
`analyzers.quality` / `foundation.*` phases, none of which is touched here.

## Contract

- Zero-argument, stateless: no `__init__` override, exactly like the five earlier
  `Structural*Extractor` classes.
- `extract(self, parse_result: ParseResult) -> FoundationExtractionResult` — identical signature
  to the abstract method it implements.
- First action: `require_successful_parse(parse_result)`, the already-existing, already-tested
  helper from `base.py`.
- One implementation, five languages: the same instance handles `ParseResult`s from every one of
  `PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, and `CppParser`. Verified
  directly (`test_single_extractor_instance_handles_all_five_languages`), not merely assumed.

## Field mapping

| `FoundationCandidate` field | Class (`cls` in `parse_result.classes`) | Function (`function` in `parse_result.functions`) |
|---|---|---|
| `name` | `cls.name` | `function.name` |
| `kind` | `FoundationCandidateKind.CLASS` | `FoundationCandidateKind.FUNCTION` |
| `relative_path` | `parse_result.relative_path` | `parse_result.relative_path` |
| `is_public` | `cls.name` is in `{export.name for export in parse_result.exports}` | `function.name` is in `{export.name for export in parse_result.exports}` |
| `has_docstring` | `cls.docstring is not None` | `function.docstring is not None` |
| `signals` | `()` | `()` |
| `line_number` | `cls.line_number` | `function.line_number` |

The export-name set is built once per `extract` call (a `frozenset`) and reused for every
candidate; that is an implementation detail with results identical to evaluating the set
comprehension per candidate.

## `is_public` means export-list membership only

`is_public` means exactly one thing in this extractor: **the candidate's name is present in the
parser's existing export-name list.** It does not mean the language-semantic notion of public
visibility is known. No naming convention, underscore rule, capitalization rule, access modifier,
or language-specific visibility rule is consulted here, and there is no "unknown" state — the
field stays a plain `bool`, exactly as the frozen `FoundationCandidate` defines it.

`parse_result.exports` is a tuple of `ParsedExport` objects, not strings. Comparing a name string
directly against it (`name in parse_result.exports`) is therefore always False — and is rejected
by `mypy --strict` as a non-overlapping container check — so the comparison is against each
export's `.name`. This is asserted explicitly
(`test_is_public_compares_against_export_name_not_the_export_object`), which proves both halves
at once: the direct comparison is False for a name that really is exported, while the extractor
correctly reports it public. (This was the one wording correction made to the lock text before
implementation: the intended semantics — "present in the parser's export list" — only hold with
the `.name` reading.)

Consequences, all consequences of what the parsers already produce (see *Known parser-level
limitations* below):

- A Python file without `__all__` produces `is_public=False` for every candidate, and so does
  every ordinary (non-module) C++ file. That means "not in the parser's export list" — it does
  not prove the construct is private in any language-semantic sense.
- Go, Rust, and TypeScript produce exact export-list membership according to their existing
  parser behavior, with the edge cases listed below.
- An export never creates a candidate: a name that is exported but is not a `ParsedClass` or
  free `ParsedFunction` (a Go `interface`, a Rust `trait`, a constant) is simply not emitted.

## `signals=()` is intentional

Every candidate has `signals=()`, in all five languages, whether a class or a function. This is
the locked initial behavior of this first concrete extractor, not an omission:

- No closed signal vocabulary exists anywhere in the frozen repository. The `FoundationCandidate`
  docstring's examples (`"no base classes"`, `"decorated with @dataclass"`) are illustrative,
  and no other doc, test, or producer defines any signal string — the examples in the frozen
  tests and Port docstrings are even mutually inconsistent, so none of them is a vocabulary.
- Downstream comparison depends on exact tuple equality (`FoundationComparer`'s verdict rules), so
  any signal string emitted here would silently become part of a comparison contract.
- Signal inputs the parsers do carry are language-uneven (`decorators` is populated only for
  Python; Go's `base_classes` is always empty by design), so a single string such as
  `"no base classes"` would mean different things per language. The test
  `test_signals_are_always_empty` shows a decorated Python class with a base class still yields
  `()`.

Downstream consequences of `signals=()`, stated plainly so they are not discovered later:
signal-based `CONFLICTING` and `COMPATIBLE` comparer outcomes remain **unreachable** until a
future contract explicitly defines signals, and `EQUIVALENT` becomes vacuously true for any two
same-name, same-kind candidates (identical empty tuples). Anything that depends on those verdicts
(the selector's conflicting-with-selected rejection, the merger's conflict check) therefore
cannot fire. **Adding signals later is a separate contract change**, and it would change comparer
verdicts for candidates produced before it.

## `has_docstring` uses `docstring is not None`

Exactly `docstring is not None`, never a truthiness check — the same rule the AST extractor
locked for its documented counts. A docstring that is the empty string (`""""""` or a
whitespace-only docstring in Python, both of which `ast.get_docstring` returns as `""`; a bare
`///` line in Rust or C++, which share one comment-collecting helper) is still present and still
counts as documented. Verified explicitly
(`test_empty_string_docstring_still_counts_as_documented`, which asserts the parser's own
docstrings are `""` before asserting the candidates). TypeScript never produces an empty-string
docstring (an empty JSDoc block yields `None`).

## Output order

1. All `CLASS` candidates, in `parse_result.classes` order.
2. All `FUNCTION` candidates, in `parse_result.functions` order.

Source order is preserved within each group, and nothing is sorted — not by name, not by line
number. `test_all_classes_precede_all_functions_and_nothing_is_sorted_by_line` proves the
distinction: a function declared on line 1 still comes out after a class declared on line 5.

## Duplicates are preserved

Every parsed class and function produces a candidate, exactly as parsed. This extractor does
**not** deduplicate, merge overloads, merge docstrings, choose a winning line, alter
`(relative_path, name)` identity, or add an owner or kind into identity. If several candidates
share a `(relative_path, name)`, all are emitted in source order, each keeping its own
`line_number` and its own `has_docstring`. This matches the precedent set by
`StructuralSymbolExtractor`. Duplicates arise from ordinary code: Python `@overload` stubs, a
redefined function, TypeScript and C++ overloads, multiple Go `init` functions, same-named Rust
functions in different inline `mod` blocks, and a class and a function sharing a name. Verified
directly (`test_duplicate_classes_produce_two_candidates`,
`test_duplicate_functions_produce_two_candidates`,
`test_class_and_function_with_the_same_name_are_both_emitted`, and end to end in the integration
test).

## Downstream duplicate subject/node identity limitation

**Downstream, the concrete `foundation.comparer.build_subjects` may reject duplicate candidates.**
It derives each `FoundationSubject.subject_id` from the repository plus
`build_qualified_name(relative_path=..., name=...)` — no owner and no kind participate — and raises
`ValidationError` when two candidates resolve to the same subject identity. The knowledge-graph
Port uses the same scheme for capability node ids (`capability_node_id`) and its
`KnowledgeGraph` rejects duplicate node identifiers. So a file that legitimately produces two
candidates with one name — any of the duplicate sources above — is a valid extractor output that
a downstream aggregation step can refuse. `build_subjects` also rejects a failed
`FoundationExtractionResult` in its input, so returning a failed result would not avoid this.

This is a downstream identity/aggregation concern. This per-file, mechanical extractor is not
permitted to invent a solution for it — no deduplication, no identity change, no new field — and
does not. Resolving it requires its own future contract decision at the aggregation layer.

## Methods are excluded

Methods are never emitted. `FoundationCandidateKind` contains only `CLASS` and `FUNCTION`, and
`FoundationCandidate` has no owner field, so a method could not be represented without inventing
a new kind or a new identity rule — and, because subject identity ignores owner, method
candidates would collide with each other and with free functions (`__init__` in two classes).
`parse_result.functions` is by definition free functions only ("methods live on their owning
`ParsedClass` instead"), which is why sourcing functions from it excludes methods by
construction. Verified directly (`test_methods_are_not_emitted`, plus the per-language cases,
each of whose sources contains a method that never appears).

For the same reason, constructs the parsers surface only as `ParseResult.symbols` — TypeScript
and Go `interface`s, Rust `trait`s, enums, type aliases — are never candidates, because they are
not `ParsedClass` entries. Verified for a Go `interface`, a TypeScript `interface`, and a Rust
`trait` (`test_go_interface_is_not_a_candidate`, `test_typescript_interface_is_not_a_candidate`,
`test_rust_trait_is_not_a_candidate`).

## Failure behavior

Exactly one error path: a failed input `ParseResult` causes `require_successful_parse` to raise
`ValidationError` immediately, uncaught, unchanged from its existing behavior. No new exception
type was introduced. `FoundationExtractionResult.failed(...)` is never constructed by this
implementation — once given a successful `ParseResult`, the mapping above is total; there is no
partial-failure case for this concern to express as data. A successful `ParseResult` with no
classes and no functions produces `FoundationExtractionResult.ok(..., candidates=())`.

## Known parser-level limitations (disclosed, not worked around)

None of these is a defect in `StructuralFoundationExtractor` — each is a property of what the
already-frozen parser layer does or does not carry into `ParseResult`, and none is fixed here (no
parser was modified). Each is asserted explicitly in the unit tests, with the parser's own output
checked first.

Export-list limitations (these determine `is_public`):

- **Python:** exports are only the literal `__all__ = [...]` (or tuple) assignment. Without
  `__all__` there are none; a name added by `__all__ += [...]` is not captured
  (`test_python_all_augmented_assignment_is_not_captured`).
- **Go:** exports are capitalized top-level names, already computed by `GoParser`; exact for
  structs and free functions. (Go methods are not in the export list, and are not emitted anyway.)
- **Rust:** any declaration whose line starts with `pub` is exported, including restricted forms
  such as `pub(crate)` (`test_rust_restricted_visibility_counts_as_exported`). The parser's
  patterns tolerate indentation, so items inside inline `mod` blocks are collected as if
  top-level.
- **TypeScript:** `export`-prefixed declarations and `export { ... }` lists. For a renamed
  export (`export { B as Renamed }`) the export list holds the alias `Renamed`, not the declared
  name `B`, so class `B` reads `is_public=False`
  (`test_typescript_renamed_export_is_reported_under_the_alias`). Member access modifiers
  (`public`/`private`/`protected`) are never stored by the parser.
- **C++:** only C++20 `export`-prefixed declarations. Ordinary C++ has no export concept, so its
  export list is empty and every candidate is `is_public=False`
  (`test_cpp_export_limitation`). Access specifiers (`public:`/`private:`) are not represented.

Docstring limitations (these determine `has_docstring`):

- **Go never carries any docstring at all.** `GoParser` never sets `docstring` on any
  `ParsedClass` or `ParsedFunction`, so every Go candidate has `has_docstring=False` regardless of
  how well the source is documented with `//` comments. Verified with genuinely documented Go
  source (`test_go_docstring_limitation`, and end to end in the integration test). Because Go's
  `is_public` is exact while its `has_docstring` is always False, exported Go candidates always
  read as public-but-undocumented.
- **Rust** attaches only `///` lines directly above a declaration; a doc comment separated from
  it by an attribute line such as `#[derive(...)]` is not attached, so `has_docstring=False`
  (`test_rust_doc_comment_separated_by_an_attribute_is_not_attached`).
- **TypeScript** can attach an unrelated earlier `/** ... */` block to a declaration whose
  preceding line ends a plain `/* ... */` comment, producing a false-positive
  `has_docstring=True` (`test_typescript_plain_block_comment_can_inherit_an_earlier_jsdoc`). The
  extractor copies the parser's answer.
- TypeScript and C++ never carry a docstring for in-class methods; irrelevant here because
  methods are never emitted.

Scope limitation: "top-level function" means whatever the parser places in
`parse_result.functions`. The parsers do not always restrict this to true top level (Rust items
inside inline `mod` blocks, for example), and this extractor passes that through unchanged.

## Tests

`tests/unit/extractors/foundation/test_base.py` — pre-existing, unchanged, still passing.

`tests/unit/extractors/foundation/test_structural.py` — 40 new tests: class and function
extraction; documented and undocumented class and function; the empty-string docstring case;
exported and non-exported names, the `export.name` comparison proof, and an exported name that
is not a class or function; `signals=()` (with a decorated, subclassed Python class); duplicate
classes, duplicate functions, and a class and function with the same name; class and function
source order and the classes-before-functions/no-sorting-by-line proof; methods excluded; Go
`interface`, TypeScript `interface`, and Rust `trait` excluded; an empty `ParseResult`; the
`ValidationError` failure path; an `isinstance` check against the `FoundationExtractor` Port
itself and a zero-argument/stateless check; the Go docstring limitation and the C++ export
limitation; one real-parser case per language (Python, Go, Rust, TypeScript, C++) plus one
"single instance, five languages" case; and the documented parser-level limitations above. Every
language case parses a real source snippet with the real parser — no hand-built `ParsedClass`,
`ParsedFunction`, or `ParsedExport` stands in for parser output. Every expected value was
obtained by running the real parser and the real extractor together and reading off the result.

## Integration test

`tests/integration/test_foundation_extraction.py` — new, self-contained (its own local `_config`,
`_all_parsers`, `_clone_repository_func`, `_enumerate_files`, `_parse_files_func`, `_run_git`;
does not import from `tests/integration/test_reference_flow.py` or any other integration module,
matching this repository's convention of self-contained test modules). Creates one real local
git repository under `tmp_path` with `shapes.py` (an exported, documented class with a method
that must not be emitted; a private undocumented class; an exported, documented function; a
private undocumented function), `duplicates.py` (two `render` functions, the second documented),
and `greeter.go` (a genuinely `//`-documented exported struct and function), runs the Reference
Flow's existing three steps plus one new `extract_foundation` `MapStep`
(`input_key="parse_results"`, `output_key="foundation_results"`,
`func=StructuralFoundationExtractor().extract`) through `bootstrap(config, extra_steps=[...])`, and
asserts the exact resulting `FoundationCandidate` tuples for all three files — including both
duplicate `render` candidates with their own lines and docstring flags, and the Go file's
`is_public=True` / `has_docstring=False` pair, verified end to end through the real flow. No
network is involved. Requires the real `git` executable; skipped, not failed, when unavailable.

## Verification results

Run against `HEAD` = `87e1bf9`, Python 3.13.13 (installed into this sandbox via
`uv python install 3.13` into a virtual environment outside the repository, specifically to match
the pinned `requires-python = ">=3.13"`, since the base environment only had 3.12). The baseline
before this implementation was verified first: 1401 passed, `mypy --strict` clean over 126 source
files, and `ruff check` showing only the one pre-existing `UP046` finding.

- `pytest tests/unit/extractors/foundation/test_structural.py -q` — **40 passed**.
- `pytest tests/integration/test_foundation_extraction.py -q` — **1 passed**.
- `mypy --strict src/` — Success: no issues found in **127** source files (126 before this
  implementation, +1 for `structural.py`).
- `ruff check src/ tests/` — exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py`; zero new findings. Left unmodified, per instructions.
- `pytest -q` (full suite) — **1442 passed**, 0 failed, the same 2 pre-existing, unrelated
  deprecation warnings as before this work. 1401 (baseline) + 40 + 1 = 1442.

The unit and integration tests were also mutation-checked against a throwaway copy outside the
repository: reintroducing a direct string-versus-`ParsedExport` comparison, truthiness instead of
`is not None`, sorting by line number, reversing the class/function order, deduplicating, emitting
a signal, forcing `is_public` False, mislabeling the kind, and skipping
`require_successful_parse` each made at least one test fail.

## Changed files

New files only:

```
src/extractors/foundation/structural.py
tests/unit/extractors/foundation/test_structural.py
tests/integration/test_foundation_extraction.py
docs/extractor_foundation_summary.md
```

## Confirmation that frozen files were untouched

`git status --short` / `git diff --stat` against `HEAD` (`87e1bf9`) show no changes to any
tracked file — the only changes are the four new, untracked files above.
`src/extractors/foundation/base.py`, `tests/unit/extractors/foundation/test_base.py`, and
`tests/integration/test_reference_flow.py` (frozen as a milestone) are confirmed byte-for-byte
unchanged. No `src/parsers/*` file and no `src/domain/*` file changed. No other extractor concern
(`imports`, `ast`, `symbols`, `architecture`, `interfaces`, `patterns`) was touched, and no
downstream Port (`analyzers.quality`, `foundation.*`) was modified. `pyproject.toml` has zero
diff — no new dependency was declared in the manifest (dev/runtime dependencies were installed
directly into this sandbox's environment to run verification, per `pyproject.toml`'s own
already-declared `[project.optional-dependencies] dev` list, plus `mypy`/`ruff` as standalone
tooling). No registry, orchestration, or dependency-boundary exemption was added. No commit, tag,
or push was made.
