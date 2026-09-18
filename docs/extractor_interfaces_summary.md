# Concrete Extractor Summary: `StructuralInterfaceExtractor`

Not a numbered phase. An additive concrete implementation of the already-frozen Phase 6
`InterfaceExtractor` Port, approved and scoped by the Interfaces Extractor Contract Discovery and
Final Contract Lock passes this implements (fifth concrete extractor, after `imports`,
`ast`/`symbols`, and `architecture`).

## Responsibility

`StructuralInterfaceExtractor` (`src/extractors/interfaces/structural.py`) turns one file's
already-parsed `ParseResult` into its `ExtractedInterface` entries — the file's interface-shaped
declarations, across every source-language form `src.parsers` can produce. It performs no
inheritance resolution, no cross-file analysis, no deduplication, and no judgment about whether
an interface is well-designed or worth reusing; see `InterfaceExtractor`'s own `base.py`
docstring for what is deliberately out of scope.

## Contract

- Zero-argument, stateless: no `__init__` override, exactly like `StructuralImportExtractor`,
  `StructuralAstExtractor`, `StructuralSymbolExtractor`, and `StructuralArchitectureExtractor`.
- `extract(self, parse_result: ParseResult) -> InterfaceExtractionResult` — identical signature
  to the abstract method it implements.
- First action: `require_successful_parse(parse_result)`, the already-existing, already-tested
  helper from `base.py`.
- One implementation, five languages: the same instance handles `ParseResult`s from every one of
  `PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, and `CppParser`. Verified directly
  (`test_single_extractor_instance_handles_all_five_languages`), not merely assumed from the
  contract.

## Two disjoint sources, no combining rule needed

`ExtractedInterface` entries come from two mutually exclusive `ParseResult` collections:

1. `parse_result.symbols` where `kind` is `SymbolKind.INTERFACE` (Go, TypeScript) or
   `SymbolKind.TRAIT` (Rust) — a language-native construct, copied through as-is.
2. `parse_result.classes` where `base_classes` names one of four locked Python spellings — a
   class recognized as structurally interface-like.

None of the five parsers ever emits `SymbolKind.INTERFACE`/`TRAIT` for a Python construct, and
none of the four non-Python parsers ever populates `base_classes` with one of the four locked
spellings, so the two sources never collide in practice. No merge, dedup, or priority rule was
needed or written; the three resulting groups are simply concatenated.

## Locked Python ABC/Protocol spelling set

Closed, exact-string-equality match against `cls.base_classes`:

```
{"ABC", "abc.ABC", "Protocol", "typing.Protocol"}
```

No fuzzy matching, no substring matching, no import-alias resolution (`import abc as _abc` would
not match `_abc.ABC`), no `typing_extensions.Protocol`, no `collections.abc.ABC`, no `ABCMeta`,
no spelling beyond these four. This set was ambiguous during contract discovery — three
independent passages in the frozen `base.py`/`docs/phase6_summary.md` text named overlapping but
non-identical subsets — and was explicitly locked to this exact four-literal set before this
implementation began, closing that ambiguity rather than resolving it unilaterally during coding.
Verified for all four spellings independently
(`test_python_class_with_bare_abc_base_is_extracted`,
`test_python_class_with_abc_dot_abc_base_is_extracted`,
`test_python_class_with_bare_protocol_base_is_extracted`,
`test_python_class_with_typing_dot_protocol_base_is_extracted`), each against real `PythonParser`
output, not a hand-built `ParsedClass`.

## Locked `ABSTRACT_CLASS` trigger rule

A `ParsedClass` becomes `InterfaceOrigin.ABSTRACT_CLASS` **if and only if** `base_classes`
contains at least one of the four literals above. An `@abstractmethod`-decorated method is never,
on its own, an independent trigger — it changes nothing when an approved base is already present,
and does not compensate for one that is absent. Verified with the two locked cases explicitly
(`test_abstractmethod_without_approved_base_is_not_extracted`:
`@abstractmethod` with no approved base → not extracted;
`test_approved_base_with_abstractmethod_is_extracted`: approved base plus `@abstractmethod` →
extracted, same as the base alone would produce), plus an ordinary class with neither
(`test_ordinary_python_class_is_not_extracted`).

## Field mapping

| `ExtractedInterface` field | `LANGUAGE_INTERFACE` / `TRAIT` source | `ABSTRACT_CLASS` source |
|---|---|---|
| `name` | `symbol.name` | `cls.name` |
| `relative_path` | `parse_result.relative_path` | `parse_result.relative_path` |
| `method_signatures` | `()` — `ParsedSymbol` has no method list | `tuple(m.name for m in cls.methods)` |
| `base_interfaces` | `()` — `ParsedSymbol` has no base list | `cls.base_classes`, verbatim |
| `line_number` | `symbol.line_number` | `cls.line_number` |

`method_signatures` is bare declared method names, not rendered call signatures — the frozen
`base.py` docstring defines the field this way explicitly, so `tuple(method.name for method in
cls.methods)` required no interpretation. Verified directly
(`test_method_signatures_are_mapped_to_bare_method_names`, two methods, both names present in
source order). `base_interfaces` is `cls.base_classes` copied without modification, including any
non-matching base alongside the approved one — verified with a two-base class
(`test_base_interfaces_is_copied_verbatim_from_base_classes`: `(Mixin, ABC)` → `base_interfaces
== ("Mixin", "ABC")`, not filtered down to only the approved literal). The native-symbol empty
fields are verified directly too
(`test_native_interface_and_trait_have_empty_method_signatures_and_base_interfaces`), against
real Go and Rust output.

## Output order

Fixed: all `LANGUAGE_INTERFACE` entries, then all `TRAIT` entries, then all `ABSTRACT_CLASS`
entries, matching the precedent set by `StructuralSymbolExtractor`'s own fixed group order.
Source order is preserved within each group and duplicates are never merged.

The cross-group order was verified by `test_output_order_is_language_interface_then_trait_then_
abstract_class`, which — uniquely among this file's tests, and documented as such in its own
docstring — combines three genuinely real, independently-parsed fragments (a real Go `interface`,
a real Rust `trait`, a real Python `ABC` class) into one synthetic `ParseResult`. This was
necessary because no single real source file can exercise all three `InterfaceOrigin` values at
once: each is exclusive to a different language/construct. Every `ParsedSymbol`/`ParsedClass`
value combined is genuine, unmodified real parser output; only their assembly into one
`ParseResult` is synthetic — no fake parser behavior was introduced. Within-group source order was
verified separately and normally, with real multi-declaration source snippets per language
(`test_source_order_preserved_among_multiple_go_interfaces`,
`..._multiple_rust_traits`, `..._multiple_python_abc_classes`).

## C++ pure-virtual limitation (explicitly not solved here)

`InterfaceOrigin.ABSTRACT_CLASS`'s own docstring names "a C++ class of pure-virtual methods" as
an intended case, but this cannot be recognized from the frozen parser DTOs:
`src/parsers/cpp/parser.py` explicitly discards the `virtual` keyword as prefix noise when
building a method's parsed record (`word not in ("virtual", "static", "explicit", "inline",
"friend", "constexpr")`), and no `= 0` pure-virtual marker is captured anywhere. `ParsedFunction`
has no field this could be derived from. `StructuralInterfaceExtractor` does not re-scan source
text to recover it, and does not modify `CppParser` — both explicitly out of scope. A C++ class
composed entirely of pure-virtual methods is therefore never recognized as `ABSTRACT_CLASS`,
regardless of its design intent. Verified explicitly
(`test_cpp_pure_virtual_class_is_not_extracted_due_to_parser_limitation`, a real
`virtual double area() = 0;` method, asserting `interfaces == ()`). This is a known, accepted
scope gap in the frozen contract itself, not a defect introduced by this implementation —
matching the precedent `StructuralArchitectureExtractor` set for its own documented Go
package-root-marker gap, and `StructuralSymbolExtractor` set for its own documented `CONSTANT`
scope gap.

## No cross-file analysis

Every `ExtractedInterface` is derived from exactly one `ParseResult` in isolation. Nothing here
reads sibling files or resolves an interface's full implementer list — matching
`InterfaceExtractor`'s own `base.py` docstring, which places that firmly outside this Port's
responsibility.

## Failure behavior

Exactly one error path: a failed input `ParseResult` causes `require_successful_parse` to raise
`ValidationError` immediately, uncaught, unchanged from its existing behavior. No new exception
type was introduced. `InterfaceExtractionResult.failed(...)` is never constructed by this
implementation — once given a successful `ParseResult`, the mapping above is total; there is no
partial-failure case for this concern to express as data.

## Tests

`tests/unit/extractors/interfaces/test_base.py` — pre-existing, unchanged, still passing.

`tests/unit/extractors/interfaces/test_structural.py` — 23 new tests: the three native
interface/trait cases (Go, TypeScript, Rust), the four locked Python spelling cases, the two
locked trigger-rule cases plus an ordinary-class negative case, `method_signatures` mapping,
`base_interfaces` verbatim copy, native-symbol empty-field verification, the fixed cross-group
output order, within-group source-order preservation (one case per language), an empty
`ParseResult`, the `ValidationError` failure path, duplicate-entry preservation, an `isinstance`
check against the `InterfaceExtractor` Port itself, the C++ pure-virtual limitation, and one
"single instance, five languages" case. Every language case parses a real source snippet with the
real parser — no hand-built `ParsedSymbol`/`ParsedClass` stands in for parser output, except the
one explicitly-documented synthetic combination described above.

## Integration test

`tests/integration/test_interfaces_extraction.py` — new, self-contained (its own local
`_config`, `_clone_repository_func`, `_enumerate_files`, `_parse_files_func`, `_run_git`; does not
import from `tests/integration/test_reference_flow.py` or `test_architecture_extraction.py`,
matching this repository's convention of self-contained test modules). Creates one real local git
repository under `tmp_path` with a real Go `interface` (`greeter.go`), a real Rust `trait`
(`writer.rs`), a real TypeScript `interface` (`reader.ts`), and a real Python `ABC` class with an
`@abstractmethod` method (`shape.py`), runs the Reference Flow's existing three steps plus one new
`extract_interfaces` `MapStep` (`input_key="parse_results"`, `output_key="interface_results"`,
`func=StructuralInterfaceExtractor().extract`) through `bootstrap(config, extra_steps=[...])`, and
asserts the real resulting `ExtractedInterface` data for all four files — including the Python
file's `method_signatures == ("area",)` and `base_interfaces == ("ABC",)`, proving the
`@abstractmethod` decorator changed nothing once the approved base was already present. Requires
the real `git` executable; skipped, not failed, when unavailable.

## Verification results

Run against this checkout (`HEAD` = `cd1d4f0`), Python 3.13.13 (installed into this sandbox via
`uv python install 3.13` specifically to match the pinned `requires-python = ">=3.13"`, since no
3.13 interpreter was present in the base environment — unlike the `architecture` extractor's own
verification pass, this run did not need to fall back to 3.12):

- `pytest tests/unit/extractors/interfaces/test_structural.py -q` — **23 passed**.
- `pytest tests/integration/test_interfaces_extraction.py -q` — **1 passed**.
- `mypy --strict src/` — Success: no issues found in **126** source files (125 before this
  implementation, +1 for `structural.py`).
- `ruff check src/ tests/` — exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py`; zero new findings. Left unmodified, per instructions.
- `pytest -q` (full suite) — **1401 passed**, 0 failed, the same 2 pre-existing, unrelated
  deprecation warnings as before this work (`starlette`/`httpx`). 1377 (baseline, verified before
  this implementation) + 23 + 1 = 1401.

## Changed files

New files only:

```
src/extractors/interfaces/structural.py
tests/unit/extractors/interfaces/test_structural.py
tests/integration/test_interfaces_extraction.py
docs/extractor_interfaces_summary.md
```

## Confirmation that frozen files were untouched

`git status --short` / `git diff --stat` against `HEAD` (`cd1d4f0`) show no changes to any
tracked file — the only changes are the four new, untracked files above.
`src/extractors/interfaces/base.py`, `tests/unit/extractors/interfaces/test_base.py`, and
`tests/integration/test_reference_flow.py` (frozen as a milestone) are confirmed byte-for-byte
unchanged. No `src/parsers/*` file and no `src/domain/*` file changed. No other extractor concern
(`ast`, `imports`, `symbols`, `architecture`) was touched. `pyproject.toml` has zero diff — no new
dependency was declared in the manifest (dev/runtime dependencies were installed directly into
this sandbox's environment to run verification, per `pyproject.toml`'s own already-declared
`[project.optional-dependencies] dev` list, plus `mypy`/`ruff` as standalone tooling, exactly as
for the `architecture` extractor's own verification pass). No dependency-boundary exemption was
added for `extractors` or anywhere else. No commit, tag, or push was made.
